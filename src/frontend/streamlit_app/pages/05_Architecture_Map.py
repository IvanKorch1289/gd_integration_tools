"""
05_Architecture_Map.py — Sprint 19 K5 W4: Interactive Architecture Map (D3.js)

Визуализирует архитектуру GD Integration Tools как интерактивный
force-directed graph (D3.js v7) в Streamlit.

Layers:
    1. Gateway         — MCP Gateway, FastAPI entrypoint
    2. AI Services     — RAG, LangMem, LLM Gateway
    3. Business Logic  — DSL Engine, Workflow, Agents
    4. Integration     — Connectors (Redis, KeyDB, DB, email, etc.)
    5. Infrastructure — Postgres, Qdrant, Redis, NATS, Vault
    6. Frontend        — Streamlit App, Admin React

Interaction:
    - Drag nodes
    - Hover for description
    - Click to show detail panel
    - Zoom / pan
    - Layer filter buttons
"""

from __future__ import annotations

import streamlit as st

__all__ = ()


# ── D3.js HTML scaffold ────────────────────────────────────────────────────

_D3_HTML = r"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ margin: 0; background: #0e0e14; overflow: hidden; font-family: sans-serif; }}
    svg {{ width: 100vw; height: 100vh; display: block; }}
    .node circle {{ stroke: #fff; stroke-width: 1.5px; cursor: grab; }}
    .node circle:hover {{ stroke: #ffd700; stroke-width: 2.5px; }}
    .node text {{ font-size: 11px; fill: #ccc; pointer-events: none; text-anchor: middle; }}
    .link {{ stroke: #444; stroke-opacity: 0.6; stroke-width: 1.2px; }}
    .link-label {{ font-size: 9px; fill: #666; }}
    #legend {{
      position: absolute; top: 16px; left: 16px;
      background: rgba(20,20,30,0.88); border: 1px solid #333;
      border-radius: 8px; padding: 12px 16px;
      color: #ccc; font-size: 12px;
    }}
    #legend h3 {{ margin: 0 0 8px; color: #fff; font-size: 13px; }}
    .legend-item {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
    .legend-dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}
    #detail {{
      position: absolute; top: 16px; right: 16px;
      background: rgba(20,20,30,0.92); border: 1px solid #333;
      border-radius: 8px; padding: 14px 18px;
      color: #ccc; font-size: 12px; max-width: 260px;
      display: none;
    }}
    #detail h3 {{ margin: 0 0 8px; color: #ffd700; font-size: 14px; }}
    #detail p {{ margin: 4px 0; line-height: 1.5; }}
    .filter-btn {{
      background: #1e1e2e; border: 1px solid #444; color: #aaa;
      padding: 4px 10px; border-radius: 12px; cursor: pointer;
      font-size: 11px; margin: 2px;
    }}
    .filter-btn:hover {{ border-color: #ffd700; color: #ffd700; }}
    .filter-btn.active {{ background: #2a2a4a; border-color: #646cff; color: #fff; }}
  </style>
</head>
<body>
<div id="legend">
  <h3>Layers</h3>
  <div id="filters"></div>
</div>
<div id="detail">
  <h3 id="detail-name"></h3>
  <p id="detail-desc"></p>
  <p id="detail-tech" style="color:#888;font-size:11px;"></p>
</div>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const DATA = [
  // ── Layer 0: Gateway ──────────────────────────────────────────────
  {{id:"mcp-gateway",    label:"MCP Gateway",      layer:0, color:"#7c3aed", desc:"Model Context Protocol hub — tool registry, session routing", tech:"Python 3.14 · FastMCP"}},
  {{id:"fastapi-main",   label:"FastAPI Entry",    layer:0, color:"#7c3aed", desc:"Main ASGI app — routes, middleware, lifespan", tech:"FastAPI · Uvicorn"}},
  {{id:"cors-mw",        label:"CORS Middleware",   layer:0, color:"#7c3aed", desc:"Cross-origin request handling", tech:"starlette-cors"}},

  // ── Layer 1: AI Services ────────────────────────────────────────
  {{id:"llm-gateway",    label:"LLM Gateway",       layer:1, color:"#059669", desc:"LiteLLM proxy — unified interface to OpenAI/Claude/GPT", tech:"LiteLLM · Langfuse"}},
  {{id:"rag-engine",     label:"RAG Engine",         layer:1, color:"#059669", desc:"Retrieval-Augmented Generation — embedding, vector search", tech:"Qdrant · sentence-transformers"}},
  {{id:"langmem",        label:"LangMem",            layer:1, color:"#059669", desc:"3-tier memory — episodic (PG) + semantic (Qdrant) + procedural", tech:"Qdrant · psycopg"}},
  {{id:"reranker",       label:"Cross-Encoder Reranker", layer:1, color:"#059669", desc:"Transformer-based relevance re-ranking", tech:"sentence-transformers"}},
  {{id:"ai-feedback",    label:"AI Feedback",        layer:1, color:"#059669", desc:"User feedback collection + RLM boost/penalty", tech:"RLMFeedbackProcessor"}},

  // ── Layer 2: Business Logic ──────────────────────────────────────
  {{id:"dsl-engine",     label:"DSL Engine",         layer:2, color:"#0891b2", desc:"YAML DSL parser + evaluator — routes, workflows, connectors", tech:"ruamel.yaml · JSONPath"}},
  {{id:"dsl-editor",     label:"DSL Visual Editor",  layer:2, color:"#0891b2", desc:"Monaco-based visual editor with LSP validation", tech:"Monaco · pygls"}},
  {{id:"workflow",       label:"Workflow Engine",    layer:2, color:"#0891b2", desc:"Saga pattern + compensation logic", tech:"Temporal · APScheduler"}},
  {{id:"agent-runtime",  label:"Agent Runtime",      layer:2, color:"#0891b2", desc:"Multi-agent orchestration — role assignment, context passing", tech:"DSPy · LangGraph"}},

  // ── Layer 3: Integration ─────────────────────────────────────────
  {{id:"connectors",     label:"Connectors",         layer:3, color:"#d97706", desc:"Generic connectors: Redis, KeyDB, PostgreSQL, email, HTTP", tech:"redis-py · asyncpg · aiosmtplib"}},
  {{id:"rpa",            label:"RPA Connector",      layer:3, color:"#d97706", desc:"Robocorp Playwright — browser automation for legacy systems", tech:"robocorp · playwright"}},
  {{id:"eventbus",       label:"Event Bus",          layer:3, color:"#d97706", desc:"AsyncPubSub — NATS / Redis Streams fallback", tech:"aiokafka · nats-py"}},
  {{id:"route-loader",   label:"Route Loader",       layer:3, color:"#d97706", desc:"Dynamic route discovery + hot-reload", tech:"importlib · watchfiles"}},

  // ── Layer 4: Infrastructure ────────────────────────────────────
  {{id:"postgres",       label:"PostgreSQL",          layer:4, color:"#dc2626", desc:"Primary datastore — routes, workflows, capabilities", tech:"asyncpg · SQLAlchemy 2"}},
  {{id:"qdrant",        label:"Qdrant",             layer:4, color:"#dc2626", desc:"Vector store — semantic memory, RAG embeddings", tech:"qdrant-client"}},
  {{id:"redis",         label:"Redis / KeyDB",      layer:4, color:"#dc2626", desc:"Cache, sessions, pub/sub, rate limiting", tech:"redis-py · asyncpg"}},
  {{id:"nats",          label:"NATS",               layer:4, color:"#dc2626", desc:"Event streaming, job queue", tech:"nats-py"}},
  {{id:"vault",         label:"Vault",               layer:4, color:"#dc2626", desc:"Secrets management — zero-downtime rotation", tech:"hvac · hvac-async"}},

  // ── Layer 5: Frontend ───────────────────────────────────────────
  {{id:"streamlit",      label:"Streamlit App",       layer:5, color:"#db2777", desc:"Operator UI — dashboards, logs, DSL playground", tech:"Streamlit"}},
  {{id:"admin-react",   label:"Admin React",         layer:5, color:"#db2777", desc:"Admin dashboard — feature flags, audit log, RBAC", tech:"React 18 · Vite"}},
  {{id:"mcp-client",    label:"MCP Client",          layer:5, color:"#db2777", desc:"Claude Code / IDE integration", tech:"MCP SDK"}},
];

const LINKS = [
  // Gateway → AI
  {s:"fastapi-main",  t:"mcp-gateway"},
  {s:"fastapi-main",  t:"llm-gateway"},
  // AI → RAG
  {s:"llm-gateway",   t:"rag-engine"},
  {s:"llm-gateway",   t:"langmem"},
  {s:"rag-engine",    t:"reranker"},
  {s:"langmem",       t:"rag-engine"},
  {s:"ai-feedback",   t:"langmem"},
  // Business Logic → AI
  {s:"dsl-engine",    t:"llm-gateway"},
  {s:"workflow",      t:"dsl-engine"},
  {s:"agent-runtime", t:"llm-gateway"},
  {s:"agent-runtime", t:"dsl-engine"},
  {s:"dsl-editor",    t:"dsl-engine"},
  // Integration
  {s:"dsl-engine",    t:"connectors"},
  {s:"workflow",      t:"rpa"},
  {s:"workflow",      t:"eventbus"},
  {s:"route-loader",  t:"dsl-engine"},
  // Infrastructure
  {s:"langmem",       t:"postgres"},
  {s:"langmem",       t:"qdrant"},
  {s:"connectors",    t:"redis"},
  {s:"connectors",    t:"postgres"},
  {s:"eventbus",      t:"nats"},
  {s:"eventbus",      t:"redis"},
  {s:"route-loader",  t:"vault"},
  // Frontend
  {s:"streamlit",     t:"fastapi-main"},
  {s:"admin-react",   t:"fastapi-main"},
  {s:"mcp-client",    t:"mcp-gateway"},
];

const layerNames = ["Gateway","AI Services","Business Logic","Integration","Infrastructure","Frontend"];

const width = window.innerWidth, height = window.innerHeight;

const svg = d3.select("body").append("svg").attr("viewBox", [0, 0, width, height]);

// Zoom / pan
const g = svg.append("g");
svg.call(d3.zoom()
  .scaleExtent([0.3, 3])
  .on("zoom", e => g.attr("transform", e.transform)));

// Simulation
const simulation = d3.forceSimulation(DATA)
  .force("link",   d3.forceLink(LINKS).id(d => d.id).distance(90).strength(0.4)))
  .force("charge", d3.forceManyBody().strength(-320))
  .force("center", d3.forceCenter(width/2, height/2))
  .force("y",      d3.forceY(d => 100 + d.layer * ((height-180)/6)).strength(0.06))
  .force("collide",d3.forceCollide(38));

// Links
const link = g.append("g").selectAll("line")
  .data(LINKS).join("line")
  .attr("class","link")
  .attr("stroke", d => {{
    const src = DATA.find(n=>n.id===d.s);
    return src ? src.color : "#444";
  }})
  .attr("stroke-opacity", 0.35);

// Nodes
const node = g.append("g").selectAll(".node")
  .data(DATA).join("g")
  .attr("class","node")
  .call(d3.drag()
    .on("start", (e,d) => {{ if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; }})
    .on("drag",  (e,d) => {{ d.fx=e.x; d.fy=e.y; }})
    .on("end",   (e,d) => {{ if (!e.active) simulation.alphaTarget(0); d.fx=null; d.fy=null; }}));

node.append("circle")
  .attr("r", 18)
  .attr("fill", d => d.color)
  .attr("opacity", 0.85)
  .on("click", (e,d) => showDetail(d));

node.append("text")
  .attr("dy", 30)
  .text(d => d.label);

// Tick
simulation.on("tick", () => {{
  link
    .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
    .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("transform", d => `translate(${d.x},${d.y})`);
}});

// Detail panel
function showDetail(d) {{
  const el = document.getElementById("detail");
  document.getElementById("detail-name").textContent = d.label;
  document.getElementById("detail-desc").textContent = d.desc;
  document.getElementById("detail-tech").textContent = d.tech;
  el.style.display = "block";
}}

// Legend + filters
const filtersEl = document.getElementById("filters");
const layerColors = ["#7c3aed","#059669","#0891b2","#d97706","#dc2626","#db2777"];
const activeLayers = new Set([0,1,2,3,4,5]);

layerNames.forEach((name, i) => {{
  const btn = document.createElement("button");
  btn.className = "filter-btn active";
  btn.textContent = name;
  btn.style.setProperty("--dot-color", layerColors[i]);
  btn.innerHTML = `<span class="legend-dot" style="background:${layerColors[i]}"></span> ${name}`;
  btn.onclick = () => {{
    if (activeLayers.has(i)) {{ activeLayers.delete(i); btn.classList.remove("active"); }}
    else {{ activeLayers.add(i); btn.classList.add("active"); }};
    node.style("opacity", d => activeLayers.has(d.layer) ? 1 : 0.12);
    link.style("opacity", d => {{
      const src = DATA.find(n=>n.id===d.s);
      return (src && activeLayers.has(src.layer)) ? 0.35 : 0.04;
    }});
  }};
  filtersEl.appendChild(btn);
}});
</script>
</body>
</html>
"""


def render() -> None:
    st.set_page_config(page_title="Architecture Map", page_icon="🗺️", layout="wide")
    st.title("🗺️ System Architecture Map")
    st.caption(
        "Interactive D3.js force-directed graph · drag nodes · hover · filter by layer · zoom (scroll)"
    )

    import streamlit.components.v1 as components

    components.html(_D3_HTML, height=700, scrolling=False)


if __name__ == "__main__":
    render()
