Full pipeline include FE, BE, SMTP & Agentic Integrations repo.
# Bank Reconciliation Batch File Validator & Processing Time Estimator

An enterprise-grade, end-of-day bank reconciliation platform featuring automated structural gating, agentic anomaly detection, multi-tier waterfall matching, predictive SLA estimation, and downstream publishing.

---

## 📚 Key Documentation

- **[8-Stage Pipeline Architecture](file:///c:/Projects/Hackathon/ARCHITECTURE.md)**: Complete technical specification and flow diagram of all 8 pipeline stages from raw ingestion to downstream publication.
- **[Product Specification](file:///c:/Projects/Hackathon/PRODUCT.md)**: Core business requirements, persona briefs, and user journey.
- **[Frontend Design System](file:///c:/Projects/Hackathon/FRONTEND_DESIGN_SYSTEM.md)**: UI/UX standards, typography (IBM Plex), zero-radius borders, and docked inspector guidelines.
- **[Visual Design Specification](file:///c:/Projects/Hackathon/DESIGN.md)**: High-density financial analyst workstation design philosophy.

---

## 🚀 Quick Start

### Backend (FastAPI)
```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```
- API Documentation: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`

### Frontend (Angular 19)
```bash
cd frontend
npm start
```
- Web Application: `http://localhost:4200`