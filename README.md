# Smart Contract Crawler

Crawls a smart contract and its proxy/child contracts across chains, producing
a dependency graph (SQLite + JSON) and a source-code bundle. It's the first
stage of a larger pipeline aimed at finding missing obligations, dead code,
and discrepancies in smart contracts backing real-world assets / tokenized
securities (e.g. RealT, which spans Ethereum mainnet and Gnosis Chain) — the
output here is meant to be handed to a downstream analysis/LLM step, not to
be the final answer itself.

## What it does

Given a root contract address, the crawler does a breadth-first walk of its
on-chain dependency graph, using four independent discovery strategies at
every node:

- **Proxy storage slots** (`resolvers/proxy_slots.py`) — reads well-known
  storage slots directly via `eth_getStorageAt`, so it works even on
  unverified contracts. Covers EIP-1967 (implementation + beacon), EIP-1822
  (UUPS), and the legacy zOS proxy pattern.
- **ABI sweep** (`resolvers/abi_sweep.py`) — calls every zero-argument
  `view`/`pure` function that returns a single `address`, and follows
  whatever comes back. Deliberately over-collects (`owner()`, `admin()`,
  etc. all count) — see [Confidence tags](#confidence-tags) for how noise
  gets flagged rather than dropped.
- **EIP-2535 Diamond Loupe** (`resolvers/diamond.py`) — if the ABI exposes
  `facets()`, calls it directly, since a Diamond's facet mapping lives in a
  mapping, not a fixed slot.
- **Bytecode PUSH20 scan** (`resolvers/bytecode.py`) — last-resort fallback
  for contracts with no ABI available from any source: disassembles the raw
  runtime bytecode looking for embedded 20-byte address constants
  (`bytecode_scan.py`), keeping only candidates that themselves have
  deployed code on-chain. Only runs when nothing else found a source.

A critical wrinkle: on an EIP-1967/1822/zOS proxy, the *implementation*
contract's storage-reliant getters (`owner()`, etc.) only return real values
when called *through the proxy* (delegatecall semantics), not at the
implementation's own address. So after finding one of these proxy edges,
`crawl.py` fetches the implementation's ABI and re-sweeps it against the
**proxy's** address (`abi_via_proxy:*` edges) — separately from the
implementation's own node, which still gets swept normally at its own
address. Beacon proxies are excluded from this forwarding: a beacon is
called directly, not delegatecalled, so its own sweep already reads its real
storage.

Contract source/ABI comes from **Etherscan first, Sourcify as a fallback**
(`sourcify_client.py`) — some contracts unverified on Etherscan are verified
on Sourcify, which is free and keyless. Only if both come up empty does the
bytecode scan kick in.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# edit .env and set ETHERSCAN_API_KEY (free at etherscan.io/apis)

sc-crawl crawl 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 --chain mainnet --depth 3 --max-nodes 50
```

Output lands in `./output/` by default: `graph.db` (SQLite), `graph.json`,
and `sources/<chain_id>/<address>/{abi.json,metadata.json,src/...}`.

### `.env`

```
ETHERSCAN_API_KEY=
MAINNET_RPC_URL=https://ethereum.publicnode.com
GNOSIS_RPC_URL=https://rpc.gnosischain.com
POLYGON_RPC_URL=https://polygon.publicnode.com
```

Only `ETHERSCAN_API_KEY` is required; the RPC URLs default to public
endpoints if unset. `.env` is loaded once at CLI startup — `chains.py`
deliberately reads `os.environ` lazily inside `get_chain()` rather than at
import time, so import order relative to `load_dotenv()` can't silently bake
in an empty key.

### Supported chains

`mainnet` (chain ID 1), `gnosis` (chain ID 100), and `polygon` (chain ID
137), all via Etherscan's v2 unified API (`api.etherscan.io/v2/api`, chain
selected by `chainid` param — Polygonscan's data is served through the same
endpoint, no separate key needed). Adding another chain means adding one
entry to `_CHAIN_META` in `chains.py`.

Polygon support was validated end-to-end against native USDC
(`0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359`), a real legacy-zOS proxy —
`--chain polygon` correctly resolved `FiatTokenProxy` → `FiatTokenV2_2`,
forwarded the delegatecalled `abi_via_proxy:*` getters (`owner`,
`blacklister`, `masterMinter`, `pauser`) through the proxy's own address,
and round-tripped through cache-reuse, `--resume`, `--snapshot`/`diff`, and
`render` correctly. Note: the default public RPC one might reach for first,
`https://polygon-rpc.com`, currently requires authentication (HTTP 401) —
`https://polygon.publicnode.com` is the one that actually works unauthenticated,
which is what the default above uses.

## CLI

```
sc-crawl crawl <address> [options]      Crawl a single root contract
sc-crawl batch <address...> [options]   Crawl multiple roots, sharing rate limit/cache/store
sc-crawl diff <old.json> <new.json>     Diff two saved snapshots
sc-crawl render <graph.json>            Render a graph as a Mermaid flowchart (.mmd)
```

Shared crawl options (`crawl` and `batch`):

| Flag | Default | Meaning |
|---|---|---|
| `--chain` | `mainnet` | `mainnet`, `gnosis`, or `polygon` |
| `--depth` | `5` | Max BFS depth from the root |
| `--max-nodes` | `200` | Budget per root address |
| `--out-dir` | `./output` | Where `graph.db`/`graph.json`/`sources/`/`cache*`/`snapshots` live |
| `--no-sourcify` | off | Disable the Sourcify fallback |
| `--resume` | off | Continue a previously interrupted/capped crawl instead of restarting |
| `--snapshot` | off | Also save a timestamped snapshot for later `diff` |

`batch` additionally takes any number of positional addresses and/or
`--file addrs.txt` (one address per line); addresses are de-duplicated
across both sources.

### Resuming and re-crawling

Every crawl persists its BFS frontier (the queue of not-yet-visited
addresses) to the `frontier` table, regardless of how it ends. `--resume`
picks that frontier back up — appropriate when a crawl was cut off by
`--max-nodes` or by a rate limit and you just want to keep going.

**Without** `--resume`, a crawl of the same root starts over from scratch
and revisits every node, relying on the Etherscan/Sourcify caches to keep
that cheap. This is intentional, not an oversight: the point of periodically
re-crawling the same root is to catch drift anywhere in the graph — a
changed implementation pointer, a new dependency — and that requires
actually revisiting nodes that resuming would otherwise skip as
already-known.

### Rate-limit handling

Etherscan's free tier signals its rate limit as HTTP 200 with
`{"message":"NOTOK","result":"Max rate limit reached"}`, not a real 429 —
`explorer_client.py` checks for both forms explicitly. On either, the
crawler stops immediately (never caches the rate-limited response, never
marks the in-flight node as resolved *or* unresolved — it goes back on the
frontier for `--resume` to retry). `batch` stops the entire batch, not just
the current address, rather than keep hammering an already-rate-limited API.
A local `RateLimiter` (`ratelimit.py`, default 4/s, under Etherscan's 5/s
free-tier cap) throttles proactively so this should be rare in practice.

## Confidence tags

Every edge is tagged `high` / `medium` / `low` (`confidence.py`), computed
once in `crawl.py` right before persisting — not embedded in each resolver,
so discovery stays purely mechanical and confidence policy stays in one
place:

- **high** — proxy-slot or Diamond-facet edges. Not a name guess; as
  certain as the on-chain data itself.
- **low** — bytecode PUSH20 constants (weakest signal in the pipeline), or
  an ABI-sweep getter whose name looks like an access-control pointer
  (`owner`, `admin`, `guardian`, `pauser`, `minter`, `blacklist`,
  `governance`, `deployer` — matched as a case-insensitive substring).
- **medium** — everything else from the ABI sweep: a plausible real
  dependency, still ultimately a heuristic.

Nothing is dropped based on confidence — a `low` edge is still a real
discovery, just flagged as more likely to be noise for whatever reads the
graph next (a human, or an LLM step). `sc-crawl render` uses this tag to
draw low-confidence edges as dotted arrows.

## Snapshots and diffing

`--snapshot` writes the full current graph state (nodes + edges) to
`output/snapshots/<chain_id>_<root_address>_<timestamp>.json` — a separate,
immutable file from the live `graph.json`, meant to be diffed against a
later crawl of the same root.

```bash
sc-crawl diff output/snapshots/1_0xabc..._20260101T000000Z.json \
              output/snapshots/1_0xabc..._20260201T000000Z.json
```

Reports nodes added/removed, node field changes (`name`, `verified`,
`is_proxy`, `status`), and edges added/removed. An implementation upgrade
shows up as one edge removed and one added on the same `from_address` with
the same `edge_type` (e.g. `proxy:eip1967_implementation`) — directly
visible in the report with no extra tooling. Pass `--json` for the raw diff
as JSON instead of the formatted text report.

This is the piece most directly aimed at the project's actual goal: "the
implementation changed" or "a new dependency appeared" between two crawls is
a short hop from surfacing a missing obligation or dead code path.

## Rendering

```bash
sc-crawl render output/graph.json
```

Writes a Mermaid `flowchart LR` (`.mmd`) alongside the input by default
(`--out` to override). Proxy nodes and unresolved nodes get distinct
styling; an edge target that falls outside the exported node set (e.g. cut
off by `--max-nodes`) still gets a minimal `external` node instead of being
silently dropped — that's exactly the "here's what's still opaque" signal
the crawler exists to surface. Paste the `.mmd` contents into
[mermaid.live](https://mermaid.live) or any Mermaid-aware Markdown viewer.

## Architecture

```
src/crawler/
  cli.py              argparse subcommands: crawl / batch / diff / render
  crawl.py            BFS traversal, resume/re-crawl seeding, proxy-forwarding
  models.py           ChainConfig, Node, Edge, ContractSource dataclasses
  chains.py           per-chain config, lazy env read (mainnet, gnosis, polygon)
  rpc_client.py        web3.py wrapper: storage reads, zero-arg address-getter
                       calls, get_code, Diamond Loupe calls
  explorer_client.py  Etherscan v2 client + rate-limit detection
  sourcify_client.py  Sourcify APIv2 client (fallback source)
  bytecode_scan.py    pure PUSH1-PUSH32-aware bytecode scanner
  resolvers/
    base.py           Resolver ABC + CrawlContext
    proxy_slots.py     EIP-1967 / EIP-1822 / legacy zOS
    abi_sweep.py       zero-arg address-getter heuristic
    diamond.py         EIP-2535 Diamond Loupe
    bytecode.py        PUSH20-constant fallback resolver
  confidence.py        edge confidence classification
  ratelimit.py         simple token-interval rate limiter
  cache.py             JSON file cache keyed by (chain_id, address)
  graph_store.py       SQLite store: nodes, edges, sources, frontier
  export.py            graph.json + source-bundle export (path-traversal safe)
  snapshot.py          snapshot save/diff/format
  render.py            Mermaid flowchart rendering
```

Each resolver only needs an RPC client and returns `list[Edge]`; adding a
new discovery strategy means adding one `Resolver` subclass and listing it
in `run_crawl()` — it does not need to know about caching, rate limiting, or
persistence.

### Data model

- **Node**: `chain_id`, `address`, `depth`, `name`, `verified`, `is_proxy`,
  `status` (`pending`/`resolved`/`unresolved`), `notes` (list of strings —
  resolver failures, fallback-source notices, etc).
- **Edge**: `chain_id`, `from_address`, `to_address`, `edge_type` (e.g.
  `proxy:eip1967_implementation`, `abi:owner`, `abi_via_proxy:processor`,
  `diamond:facet`, `bytecode:push20_constant`), `source` (the slot/function
  name that produced it), `confidence`.
- **ContractSource**: `chain_id`, `address`, `contract_name`, `abi`,
  `source_files` (filename → content), `compiler_version`,
  `source_provider` (`etherscan` | `sourcify`).

All of this is persisted in `graph.db` (SQLite: `nodes`, `edges`, `sources`,
`frontier` tables) and re-exported to `graph.json` / the source bundle on
every run.

## Testing

```bash
pytest
```

All tests run offline against fakes (`tests/conftest.py`: `FakeRpc`,
`FakeExplorer`, `FakeSourcify`) — no live network calls. Live behavior
(Etherscan rate-limit body shape, the real Sourcify APIv2 schema, real
proxy/Diamond contracts) was validated by hand against real mainnet/Gnosis
contracts during development, not in the automated suite, specifically to
keep CI runs from burning API quota.

## API-call discipline

Etherscan's free tier is easy to get rate-limited or temporarily banned on.
Some habits baked into the code and worth keeping in mind when testing
against live chains yourself:

- Every Etherscan/Sourcify response is cached to disk
  (`output/cache/`, `output/cache_sourcify/`) keyed by `(chain_id, address)`
  — a second run against the same contracts costs zero live calls, as long
  as the cache directory hasn't been deleted.
- Rate-limited responses are never cached and never counted as a real
  answer, so a retry doesn't silently succeed with garbage.
- Always pass `--max-nodes`/`--depth` caps when testing against a new root
  you haven't crawled before, to bound worst-case call volume up front.
