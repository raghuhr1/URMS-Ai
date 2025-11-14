# Streamlit Cloud Deployment Guide

## Deploy to Streamlit Cloud

Follow these steps to deploy the URMS Depot UI to Streamlit Cloud:

### 1. Prerequisites
- GitHub account with the repository pushed
- Streamlit Cloud account (free at https://streamlit.io/cloud)

### 2. Deployment Steps

1. Go to [Streamlit Cloud](https://share.streamlit.io)
2. Click "New app"
3. Select:
   - **Repository**: `raghuhr1/URMS-Ai`
   - **Branch**: `main`
   - **Main file path**: `urms_depot_ui_pro.py` (for enhanced version) or `urms_depot_ui.py` (for basic version)

4. Click "Deploy"

### 3. Configuration
- The app uses SQLite database (local file storage)
- Streamlit Cloud will auto-reload on code changes
- For production, migrate to PostgreSQL or cloud database

### 4. App URL
Once deployed, your app will be available at:
```
https://share.streamlit.io/raghuhr1/URMS-Ai/main/urms_depot_ui_pro.py
```

### 5. Environment Variables (Optional)
To add environment variables to Streamlit Cloud:
1. Go to your app settings
2. Navigate to Secrets
3. Add any required API keys or configuration

### 6. Local Development
To test locally before deployment:
```bash
streamlit run urms_depot_ui_pro.py
```

The app will be available at `http://localhost:8501`

### Features
- **Pro Version** (`urms_depot_ui_pro.py`): Enhanced UI with Plotly charts, modern styling, advanced analytics
- **Basic Version** (`urms_depot_ui.py`): Simplified single-file demo

### Database
- SQLite is used for demo purposes
- For production deployment, consider:
  - AWS RDS (PostgreSQL)
  - Google Cloud SQL
  - Azure Database
  - MongoDB Atlas

### Performance Tips
- Keep database queries optimized
- Use caching with `@st.cache_data` decorator
- Implement pagination for large datasets
- Monitor app memory usage in Streamlit Cloud dashboard

---
**Repository**: https://github.com/raghuhr1/URMS-Ai
**Deployed App**: Ready for Streamlit Cloud deployment
