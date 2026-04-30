# 📦 Gestion de Stock - Inventory Management System
```markdown
# Gestion de Stock - Inventory Management System

A comprehensive Django-based inventory management system with two-factor authentication, stock tracking, and PDF report generation.

## Technology Stack

- **Backend**: Django 6.0 (Python 3.13+)
- **Database**: PostgreSQL 16
- **Frontend**: HTML5, CSS3, Bootstrap 5
- **Additional Libraries**: PyOTP (2FA), xhtml2pdf (Reports), Chart.js (Dashboard charts)

## Installation

### Prerequisites
- Python 3.13 or higher
- PostgreSQL 16 or higher
- Git

### Setup

1. Clone the repository
```bash
git clone https://github.com/your-username/gestion-de-stock.git
cd gestion-de-stock
```

2. Create and activate a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Configure environment variables
```bash
cp .env.example .env
# Edit .env with your database credentials and email settings
```

5. Create the database in PostgreSQL
```sql
CREATE DATABASE gestion_stock;
```

6. Run migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

7. Create a superuser (administrator)
```bash
python manage.py createsuperuser
```

8. Collect static files
```bash
python manage.py collectstatic --noinput
```

## Running the Application

Start the development server:
```bash
python manage.py runserver
```

Access the application at: `http://127.0.0.1:8000/`

## Main Features

### Authentication
- Two-factor authentication (OTP via email)
- Account lockout after 5 failed attempts (30 minutes)
- Password complexity requirements (8 chars, uppercase, lowercase, digit)
- Forgot password functionality with email reset link

### Dashboard
- **Administrator Dashboard**: Statistics, charts, recent movements, critical products
- **Staff Dashboard**: Recent entries/exits, quick actions, product catalog modal

### Stock Management
- Create, read, update, delete products
- Stock entry documents (BonEntree) with supplier selection
- Stock exit documents (BonSortie) with client selection
- Automatic stock quantity updates
- Stock validation (cannot exceed available stock)

### User Management (Admin only)
- Add, edit, delete users
- Assign roles (User, Staff, Administrator)
- Block/unblock user accounts
- View user activity history
- Automatic temporary password generation with email delivery

### Notifications
- Real-time low stock alerts in navbar bell icon
- Email change request workflow with admin approval
- Read/unread status per user
- Mark as read / Mark all as read

### Reporting
- Generate PDF activity reports for any date range
- Top products, suppliers, and clients statistics
- Detailed movement lists
- Professional layout with official header

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/produits/` | GET | List all products |
| `/api/produits/` | POST | Create a new product |
| `/api/produits/<id>/` | GET | Get product details |
| `/api/produits/<id>/` | PUT | Update a product |
| `/api/produits/<id>/` | DELETE | Delete a product |
| `/api/notifications/<id>/read/` | POST | Mark low stock notification as read |

## Main URLs

| URL | Description |
|-----|-------------|
| `/login/` | Login page with 2FA |
| `/dashboard-admin/` | Administrator dashboard |
| `/dashboard-user/` | Staff dashboard |
| `/produits/` | Product management |
| `/bons-entree/` | Stock entry management |
| `/bons-sortie/` | Stock exit management |
| `/users/` | User management (admin only) |
| `/clients/` | Client management (admin only) |
| `/fournisseurs/` | Supplier management (admin only) |
| `/admin-report/` | Activity report generation |
| `/profile/` | User profile management |

## Email Configuration

The application uses Gmail SMTP with App Password for email notifications:

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_16_char_app_password
```

## Environment Variables (.env)

```env
SECRET_KEY=django-insecure-your-secret-key
DEBUG=False
DB_NAME=gestion_stock
DB_USER=postgres
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=5432
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
ADMIN_EMAILS=admin@example.com
```

## Database Schema

Main tables:
- `Utilisateur` - User profiles (linked to Django User)
- `Produit` - Products with stock and alert threshold
- `Client` - Client records
- `Fournisseur` - Supplier records
- `BonEntree` - Stock entry documents
- `LigneEntree` - Entry document lines
- `BonSortie` - Stock exit documents
- `LigneSortie` - Exit document lines
- `Notification` - System notifications
- `NotificationStatus` - Read status for stock alerts

## Troubleshooting

### Database connection error
- Verify PostgreSQL is running
- Check database credentials in .env file

### Email not sending
- Verify Gmail App Password is correct
- Enable 2FA on the Gmail account
- Generate an App Password from Google Account settings

### Session issues
- Run `python manage.py migrate sessions`
- Check `SESSION_ENGINE` in settings.py

## License

Academic project - University of Batna 2

## Authors

- Zerrouni Aya
- Regaa Ibtissam
- Ramdane Norhane
