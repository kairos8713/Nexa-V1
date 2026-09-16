# ☕ Nexa V1 (Prototype MVP)

*An intensive 12-day sprint full-stack SaaS prototype built to streamline café operations, synchronize digital menus, and track live workflows.*

![Flask](https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white)
![Jinja2](https://img.shields.io/badge/Jinja2-B41717?style=flat-square&logo=jinja&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-CC292B?style=flat-square&logo=sqlalchemy&logoColor=white)
![Alembic](https://img.shields.io/badge/Alembic-4A3B2C?style=flat-square)
![Socket.io](https://img.shields.io/badge/Socket.io-010101?style=flat-square&logo=socketdotio&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black)

---

## 🛠️ Development Approach

Built solo, with AI-assisted tooling (Claude Code / Antigravity) used for rapid iteration on routing logic, hardware protocol integration, and debugging. All architecture decisions, integration design, and production hotfixes were made and validated by me.

## 📌 Current MVP: Engineering Logic

Nexa V1 is a lean, single-instance platform optimized for rapid, on-site retail infrastructure validation and low-overhead operational discovery. It is currently running as a live field test inside a commercial café.

### The Ecosystem Framework

- **Core Architecture:** Built using **Flask** coupled with **Jinja2** for modular server-side template rendering and fragment generation.
- **State & Session Management:** Secured via **Flask-Login** and structured middleware execution.
- **Data Access Layer:** Powered by **SQLAlchemy ORM** with asynchronous, lightweight network triggers driven by **Flask-SocketIO** running on an **Eventlet** production worker.
- **Database Migrations:** Schema state transitions are tracked and versioned using **Alembic** (via **Flask-Migrate**), keeping structural technical debt traceable.
- **Fiscal Hardware Integration:** A custom C# bridge service (`HuginBridge`) exposes the Hugin FP300 fiscal POS printer over a local HTTP interface, called from the Flask backend.

### The SQLite Engineering Decision

While standard enterprise architectures enforce complex distributed database configurations, Nexa V1 purposefully utilizes SQLite. This was a calculated engineering constraint designed to minimize database maintenance layers during rapid validation, achieve zero-configuration execution on localized hardware, and eliminate cloud infrastructure spending during the prototype phase.

Because the data layer is fully isolated via SQLAlchemy ORM models, migrating the entire entity graph to a production PostgreSQL environment requires only changing a single connection string.

## ⚠️ Technical Debt & Operational Hotfixes

Operating inside a live commercial establishment means production uptime takes precedence over aesthetic polish.

### 1. Visual & UI/CSS Inconsistencies (Acknowledged Technical Debt)

There are known layout styling imperfections, specifically within the Dark Theme views. These are deliberately left unfixed for now, since they don't affect transaction speed or order entry. Nexa V2 will introduce a ground-up design system.

### 2. Field-Driven Emergency Hotfixes

Some routing logic carries added complexity due to immediate, production-saving patches applied live during business hours:

- **The F8 Hardware Bypass:** A key-listener hotfix injected into the dashboard template to immediately connect/disconnect the Hugin terminal interface at runtime if a hardware lockup occurs, keeping the store from freezing.
- **The Audio Autoplay Override:** Custom gesture-unlock loops to override mobile browser autoplay restrictions, ensuring kitchen and bar displays reliably trigger order alert sounds.

## 🔮 Nexa V2: Roadmap

Nexa V2 moves the system from a localized prototype toward a secure, commercial-grade, multi-tenant SaaS architecture, built around the operational data gathered from the V1 field test.

| Area | Plans |
|---|---|
| **IoT Automation** | **Nexa Bar:** Arduino/ESP32 peristaltic liquid dosing matched to POS recipes to protect material margins. **Nexa Kitchen:** Raspberry Pi + load-cell (HX711) scales letting back-of-house staff weigh ingredients to track waste and portion control. |
| **Smart ERP & Accounting** | **Scanner OCR Ingestion:** Direct image processing from office scanners, normalized via generative structuring models (e.g. Qwen) to automate stock intake and unit cost updates. |
| **Edge Computing & Sync** | **Nexa Edge:** Local containerized systems with hybrid sync — if the WAN connection drops, the store keeps operating locally and syncs to the cloud PostgreSQL node once connectivity is restored. |
| **Forecasting** | **Sales & Revenue Forecasting** *(exploring)*: Time-series modeling to predict daily/weekly revenue and inventory needs based on historical sales, day-of-week and seasonal patterns. Direction still being scoped — replaces an earlier camera-based vision concept that was dropped in favor of this data-driven approach. |

---

*Developed as a solo project by Emre Ercan.*
