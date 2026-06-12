<div align="center">
  <h1>☕ Nexa V1 (Prototype MVP)</h1>
  <p><i>An intensive 12-day sprint full-stack SaaS prototype built to streamline café operations, synchronize digital menus, and track live workflows.</i></p>

  <img src="https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white" alt="Flask" />
  <img src="https://img.shields.io/badge/Jinja2-B41717?style=flat-square&logo=jinja&logoColor=white" alt="Jinja2" />
  <img src="https://img.shields.io/badge/SQLAlchemy-CC292B?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/Alembic-4A3B2C?style=flat-square" alt="Alembic" />
  <img src="https://img.shields.io/badge/Socket.io-010101?style=flat-square&logo=socketdotio&logoColor=white" alt="Socket.io" />
  <img src="https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black" alt="JavaScript" />
</div>

<hr>

## 🛠️ Development Paradigm: 100% Solo & AI-Collaborative

This entire ecosystem—spanning full-stack web architectures, localized network fallback infrastructures, hardware bridging, and dynamic automation logic—was engineered and deployed without a single line of code written by any external human engineer.

<ul>
  <li><strong>Zero Human Outsourcing:</strong> No engineering team, no external freelancers, and no third-party software outsourcing.</li>
  <li><strong>The AI-Collaborative Framework:</strong> The architecture was built by shifting traditional team dynamics into an advanced AI co-piloting process. By utilizing AI for rapid logical iterations, micro-service design, and obscure hardware protocol validation, a single developer matched the production velocity of a complete engineering pod.</li>
</ul>

<br>

## 📌 Nexa V1: Current MVP Engineering Logic

Nexa V1 is a lean, single-instance platform optimized for rapid, on-site retail infrastructure validation and low-overhead operational discovery. It is currently running as a high-traffic live field test inside a commercial café ecosystem.

### The Ecosystem Framework
- **Core Architecture:** Built using **Flask** coupled with **Jinja2** for modular server-side template rendering and fragment generation.
- **State & Session Management:** Secured via **Flask-Login** and structured middleware execution.
- **Data Access Layer:** Powered by **SQLAlchemy ORM** with asynchronous, lightweight network triggers driven by **Flask-SocketIO** running on an **Eventlet** production worker network.
- **Database Migrations:** Schema state transitions are explicitly tracked and versioned using **Alembic** (via **Flask-Migrate**), keeping structural technical debt traceable.

### The SQLite Engineering Decision
While standard enterprise architectures enforce complex distributed database configurations, Nexa V1 purposefully utilizes SQLite. This was a calculated engineering constraint designed to minimize database maintenance layers during rapid validation, achieve zero-configuration execution on localized hardware, and completely eliminate cloud infrastructure spending during prototype phases.

Because data layers are completely isolated via SQLAlchemy ORM models, migrating the entire entity graph to a production PostgreSQL environment requires only changing a single server environment connection string variable.

<br>

## ⚠️ Technical Debt & Operational Hotfixes

Operating inside a live commercial establishment means that desk-theory software engineering always crashes against real-world operational chaos. Production uptime and workflow continuous cycles take absolute precedence over perfect aesthetic layout formatting.

### 1. Visual & UI/CSS Inconsistencies (Acknowledged Technical Debt)
There are known layout styling imperfections and color-contrast bugs, specifically within the **Dark Theme** views (such as hardcoded standard components and un-themed input layers). These are **deliberately left unfixed**. Since they do not degrade core transactions or slow down the speed of order entries, refactoring them on an early-stage prototype is a waste of engineering velocity. Nexa V2 will introduce a brand new, ground-up design system.

### 2. Field-Driven Emergency Hotfixes (The Battle Scars)
Some segments of the routing logic carry high complexity due to immediate, production-saving emergency patches applied live during business peak hours:
<ul>
  <li><strong>The F8 Hardware Bypass:</strong> A raw key-listener hotfix injected straight into the global dashboard template layout to immediately connect/disconnect the physical Hugin terminal interface at runtime if a hardware lockup occurs, keeping the store from freezing.</li>
  <li><strong>The Audio Autoplay Override:</strong> Custom gesture-unlock loops introduced to override aggressive mobile browser silent updates, guaranteeing that kitchen and bar displays reliably trigger high-frequency acoustic alert signals when new orders drop.</li>
</ul>

<br>

## 🔮 Nexa V2: The Future Closed-Source Enterprise Road

Nexa V2 moves the system from a localized prototype into a secure, commercial-grade, multi-tenant SaaS architecture engineered entirely around the operational metrics extracted from the V1 field test.

<table width="100%">
  <tr>
    <td width="30%"><b>IoT Automation Layer</b></td>
    <td>
      <strong>Nexa Bar:</strong> Integrated Arduino/ESP32 peristaltic liquid dosing systems matching physical syrup flows with POS recipes to protect material margins.<br>
      <strong>Nexa Kitchen:</strong> Localized Raspberry Pi + Load Cell (HX711) scales allowing back-of-house teams to weight un-cooked items directly into the KDS layer to track ingredient waste and portion-control anomalies.
    </td>
  </tr>
  <tr>
    <td><b>Smart ERP & Accounting</b></td>
    <td>
      <strong>Scanner OCR Ingestion:</strong> Direct image processing from local sheet-fed office scanners. Documents are normalized and parsed via generative structuring models (e.g., Qwen) to automate stock intake, entity association, and dynamic unit material cost updates.
    </td>
  </tr>
  <tr>
    <td><b>Edge-Computing & Sync</b></td>
    <td>
      <strong>Nexa Edge Infrastructure:</strong> Local containerized systems running hybrid sync algorithms. If external WAN internet goes offline, the physical store, POS networks, and camera verification continue operating locally, appending entries to an isolated transaction stream to synchronize with cloud PostgreSQL nodes when link stability is restored.
    </td>
  </tr>
  <tr>
    <td><b>AI & AI Vision</b></td>
    <td>
      <strong>Nexa Vision:</strong> Live verification using local RTSP camera security streams. When a guest submits a table order via the mobile framework, a lightweight model validates actual human occupancy at those coordinates to auto-block malicious remote spam orders.<br>
      <strong>Nexa Brain:</strong> Time-series modeling predicting inventory peaks based on weather, shifts, and localized trends, combined with predictive ROI matrices assessing which marketing media assets deliver the highest conversion rates.
    </td>
  </tr>
</table>

<hr>

<div align="center">
  <p><i>Developed as a Solo + AI Exploration by Emre Ercan.</i></p>
</div>
