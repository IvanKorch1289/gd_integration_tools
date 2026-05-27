/**
 * Architecture Graph — D3.js v7 force-directed visualization.
 * Loaded by 05_Architecture_Map.py
 */

const DATA = [
  // ── Layer 0: Gateway ──────────────────────────────────────────────
  {id:"mcp-gateway",    label:"MCP Gateway",      layer:0, color:"#7c3aed", desc:"Model Context Protocol hub — tool registry, session routing", tech:"Python 3.14 · FastMCP"},
  {id:"fastapi-main",   label:"FastAPI Entry",    layer:0, color:"#7c3aed", desc:"Main ASGI app — routes, middleware, lifespan", tech:"FastAPI · Uvicorn"},
  {id:"cors-mw",        label:"CORS Middleware",  layer:0, color:"#7c3aed", desc:"Cross-origin request handling", tech:"starlette-cors"},

  // ── Layer 1: AI Services ────────────────────────────────────────
  {id:"llm-gateway",    label:"LLM Gateway",      layer:1, color:"#059669", desc:"LiteLLM proxy — unified interface to OpenAI/Claude/GPT", tech:"LiteLLM · Langfuse"},
  {id:"rag-engine",     label:"RAG Engine",        layer:1, color:"#059669", desc:"Retrieval-Augmented Generation — embedding, vector search", tech:"Qdrant · sentence-transformers"},
  {id:"langmem",        label:"LangMem",            layer:1, color:"#059669", desc:"3-tier memory — episodic (PG) + semantic (Qdrant) + procedural", tech:"Qdrant · psycopg"},
  {id:"reranker",       label:"Cross-Encoder Reranker", layer:1, color:"#059669", desc:"Transformer-based relevance re-ranking", tech:"sentence-transformers"},
  {id:"ai-feedback",    label:"AI Feedback",        layer:1, color:"#059669", desc:"User feedback collection + RLM boost/penalty", tech:"RLMFeedbackProcessor"},

  // ── Layer 2: Business Logic ──────────────────────────────────────
  {id:"dsl-engine",     label:"DSL Engine",         layer:2, color:"#0891b2", desc:"YAML DSL parser + evaluator — routes, workflows, connectors", tech:"ruamel.yaml · JSONPath"},
  {id:"dsl-editor",     label:"DSL Visual Editor",  layer:2, color:"#0891b2", desc:"Monaco-based visual editor with LSP validation", tech:"Monaco · pygls"},
  {id:"workflow",       label:"Workflow Engine",    layer:2, color:"#0891b2", desc:"Saga pattern + compensation logic", tech:"Temporal · APScheduler"},
  {id:"agent-runtime",  label:"Agent Runtime",      layer:2, color:"#0891b2", desc:"Multi-agent orchestration — role assignment, context passing", tech:"DSPy · LangGraph"},

  // ── Layer 3: Integration ─────────────────────────────────────────
  {id:"connectors",     label:"Connectors",         layer:3, color:"#d97706", desc:"Generic connectors: Redis, KeyDB, PostgreSQL, email, HTTP", tech:"redis-py · asyncpg · aiosmtplib"},
  {id:"rpa",            label:"RPA Connector",      layer:3, color:"#d97706", desc:"Robocorp Playwright — browser automation for legacy systems", tech:"robocorp · playwright"},
  {id:"eventbus",       label:"Event Bus",          layer:3, color:"#d97706", desc:"AsyncPubSub — NATS / Redis Streams fallback", tech:"aiokafka · nats-py"},
  {id:"route-loader",   label:"Route Loader",       layer:3, color:"#d97706", desc:"Dynamic route discovery + hot-reload", tech:"importlib · watchfiles"},

  // ── Layer 4: Infrastructure ────────────────────────────────────
  {id:"postgres",       label:"PostgreSQL",          layer:4, color:"#dc2626", desc:"Primary datastore — routes, workflows, capabilities", tech:"asyncpg · SQLAlchemy 2"},
  {id:"qdrant",         label:"Qdrant",               layer:4, color:"#dc2626", desc:"Vector store — semantic memory, RAG embeddings", tech:"qdrant-client"},
  {id:"redis",          label:"Redis / KeyDB",        layer:4, color:"#dc2626", desc:"Cache, sessions, pub/sub, rate limiting", tech:"redis-py · asyncpg"},
  {id:"nats",           label:"NATS",                 layer:4, color:"#dc2626", desc:"Event streaming, job queue", tech:"nats-py"},
  {id:"vault",          label:"Vault",                layer:4, color:"#dc2626", desc:"Secrets management — zero-downtime rotation", tech:"hvac · hvac-async"},

  // ── Layer 5: Frontend ───────────────────────────────────────────
  {id:"streamlit",      label:"Streamlit App",       layer:5, color:"#db2777", desc:"Operator UI — dashboards, logs, DSL playground", tech:"Streamlit"},
  {id:"admin-react",    label:"Admin React",         layer:5, color:"#db2777", desc:"Admin dashboard — feature flags, audit log, RBAC", tech:"React 18 · Vite"},
  {id:"mcp-client",     label:"MCP Client",          layer:5, color:"#db2777", desc:"Claude Code / IDE integration", tech:"MCP SDK"},
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

(function initGraph() {
  const width = window.innerWidth, height = window.innerHeight;

  const svg = d3.select("body").append("svg").attr("viewBox", [0, 0, width, height]);

  // Zoom / pan
  const g = svg.append("g");
  svg.call(d3.zoom()
    .scaleExtent([0.3, 3])
    .on("zoom", e => g.attr("transform", e.transform)));

  // Simulation
  const simulation = d3.forceSimulation(DATA)
    .force("link",   d3.forceLink(LINKS).id(d => d.id).distance(90).strength(0.4))
    .force("charge", d3.forceManyBody().strength(-320))
    .force("center", d3.forceCenter(width/2, height/2))
    .force("y",      d3.forceY(d => 100 + d.layer * ((height-180)/6)).strength(0.06))
    .force("collide",d3.forceCollide(38));

  // Links
  const link = g.append("g").selectAll("line")
    .data(LINKS).join("line")
    .attr("class","link")
    .attr("stroke", d => {
      const src = DATA.find(n=>n.id===d.s);
      return src ? src.color : "#444";
    })
    .attr("stroke-opacity", 0.35);

  // Nodes
  const node = g.append("g").selectAll(".node")
    .data(DATA).join("g")
    .attr("class","node")
    .call(d3.drag()
      .on("start", (e,d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
      .on("drag",  (e,d) => { d.fx=e.x; d.fy=e.y; })
      .on("end",   (e,d) => { if (!e.active) simulation.alphaTarget(0); d.fx=null; d.fy=null; }));

  node.append("circle")
    .attr("r", 18)
    .attr("fill", d => d.color)
    .attr("opacity", 0.85)
    .on("click", (e,d) => showDetail(d));

  node.append("text")
    .attr("dy", 30)
    .text(d => d.label);

  // Tick
  simulation.on("tick", () => {
    link
      .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  // Detail panel
  window.showDetail = function showDetail(d) {
    const el = document.getElementById("detail");
    document.getElementById("detail-name").textContent = d.label;
    document.getElementById("detail-desc").textContent = d.desc;
    document.getElementById("detail-tech").textContent = d.tech;
    el.style.display = "block";
  };

  // Legend + filters
  const filtersEl = document.getElementById("filters");
  const layerColors = ["#7c3aed","#059669","#0891b2","#d97706","#dc2626","#db2777"];
  const activeLayers = new Set([0,1,2,3,4,5]);

  layerNames.forEach((name, i) => {
    const btn = document.createElement("button");
    btn.className = "filter-btn active";
    btn.textContent = name;
    btn.innerHTML = `<span class="legend-dot" style="background:${layerColors[i]}"></span> ${name}`;
    btn.onclick = () => {
      if (activeLayers.has(i)) { activeLayers.delete(i); btn.classList.remove("active"); }
      else { activeLayers.add(i); btn.classList.add("active"); }
      node.style("opacity", d => activeLayers.has(d.layer) ? 1 : 0.12);
      link.style("opacity", d => {
        const src = DATA.find(n=>n.id===d.s);
        return (src && activeLayers.has(src.layer)) ? 0.35 : 0.04;
      });
    };
    filtersEl.appendChild(btn);
  });
})();
