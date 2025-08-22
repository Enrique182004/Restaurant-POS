# Restaurant-POS

A comprehensive Point-of-Sale system for restaurants built with Python Flask, designed to streamline restaurant operations and enhance customer experience through modern web technologies.

# Restaurant-POS

A comprehensive Point-of-Sale system for restaurants built with Python Flask, featuring user authentication, order management, promotional systems, and receipt printing capabilities.

## 🍽️ Features

### Core Functionality
- **User Authentication**: Login system with admin and user roles
- **Menu Customization**: Interactive customization for Rice Ball, Sushi, Boneless, Beverages, and Complementos
- **Order Management**: Add items to cart, modify quantities, edit items, and remove items
- **Promotional System**: Apply coupon codes with special promotions (4x3 Sushi, 2x1 Rice Ball)
- **Payment Processing**: Cash and card payment options with change calculation
- **Receipt Printing**: Physical receipt printing with detailed order information
- **Session Management**: Persistent cart and customer information across sessions

### Technical Features
- **Responsive Design**: Dark-themed tablet-friendly interface optimized for touch
- **Database Integration**: SQLite database with orders, promotions, and users tables
- **Complex Pricing Logic**: Dynamic pricing based on ingredients, sauces, and special additions
- **Input Validation**: Client and server-side validation with ingredient limits
- **Error Handling**: Comprehensive error management and user feedback
- **Real-time Updates**: AJAX-powered quantity updates and cart management

## 🛠️ Technologies & Languages Used

### Backend
- **Python 3.7+**: Core programming language
- **Flask**: Web framework with session management
- **SQLite3**: Database for orders, users, and promotions
- **Jinja2**: Template engine for dynamic HTML generation

### Frontend
- **HTML5**: Semantic markup with accessibility features
- **CSS3**: Custom dark theme with responsive grid layouts
- **JavaScript (ES6+)**: Interactive functionality and AJAX requests

### Database Schema
- **orders**: Order tracking with JSON item storage, payment details, and customer info
- **promotions**: Configurable promotion system with multiple types
- **users**: User authentication with role-based access

### Architecture
- **MVC Pattern**: Clean separation of models, views, and controllers
- **RESTful Routes**: Organized URL structure for all operations
- **Session-Based State**: Cart and user state management
- **Component-Based UI**: Reusable card-based interface components

## 🚀 Getting Started

### Prerequisites
- Python 3.7 or higher
- pip (Python package installer)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/Restaurant-POS.git
cd Restaurant-POS
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install required dependencies:
```bash
pip install -r requirements.txt
```

4. Run the application:
```bash
python app.py
```

5. Open your browser and navigate to `http://localhost:5001`

### Default Login Credentials
- **Admin**: admin / admin123
- **User**: user / user123

## 📁 Project Structure

```
Restaurant-POS/
├── app.py                 # Main Flask application with all routes
├── restaurant.db          # SQLite database (auto-generated)
├── static/                # Static assets
│   ├── css/
│   │   ├── main.css       # Desktop/fallback styles
│   │   └── tablet.css     # Touch-optimized dark theme
│   └── js/
│       ├── common.js      # Fallback JavaScript functionality
│       └── tablet.js      # Enhanced touch interactions
├── templates/             # Jinja2 HTML templates
│   ├── login.html         # User authentication
│   ├── index.html         # Main menu with customer name input
│   ├── cart.html          # Order review with promotions
│   ├── rice_ball.html     # Rice ball customization
│   ├── sushi.html         # Sushi customization
│   ├── boneless.html      # Boneless customization
│   ├── beverages.html     # Beverage selection
│   ├── complementos.html  # Extra sauces
│   ├── payment.html       # Payment method selection
│   ├── cash_payment.html  # Cash payment with calculator
│   └── thank_you.html     # Order completion
├── receipts/              # Generated receipt files (auto-created)
├── requirements.txt       # Python dependencies
├── .gitignore            # Git ignore rules
└── README.md             # Project documentation
```

## 🔧 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET/POST` | `/login` | User authentication |
| `GET` | `/logout` | End user session |
| `GET` | `/` | Main menu (requires login) |
| `GET/POST` | `/customize/rice_ball` | Rice ball customization |
| `GET/POST` | `/customize/sushi` | Sushi customization |
| `GET/POST` | `/customize/boneless` | Boneless customization |
| `GET/POST` | `/customize/beverages` | Beverage selection |
| `GET/POST` | `/customize/complementos` | Extra sauces |
| `GET` | `/cart` | View cart and apply promotions |
| `POST` | `/update_quantity/<index>/<qty>` | Update item quantity |
| `GET/POST` | `/update_item/<index>` | Edit cart item |
| `GET` | `/remove_item/<index>` | Remove item from cart |
| `POST` | `/apply_coupon` | Apply promotional codes |
| `POST` | `/save_customer_name` | Save customer information |
| `GET` | `/payment` | Payment method selection |
| `GET` | `/cash_payment` | Cash payment interface |
| `GET/POST` | `/ticket` | Generate receipt and complete order |

## 🎯 Key Features Implementation

### Promotional System
- **SUSHI4X3**: Buy 4 sushi, pay for 3 (applies to cheapest item)
- **RICEBALL2X1**: Buy 2 rice balls, pay for 1
- Search and quick-apply promotion interface

### Dynamic Pricing
- **Rice Ball**: $115 base + $10 per Ostión
- **Sushi**: $115 prepared / $110 seco or salsas aparte + $10 per Ostión  
- **Boneless**: $105 base (includes up to 2 sauces)
- **Beverages**: $10 agua / $25 sodas
- **Complementos**: $10 per extra sauce

### Ingredient Validation
- **Rice Ball**: 1-6 regular ingredients + optional Ostión (7th)
- **Sushi**: 1-3 regular ingredients + optional Ostión (4th)
- Real-time validation prevents exceeding limits

### Receipt System
- Generates detailed text receipts with itemized customizations
- Automatic printer integration for Windows/Mac/Linux
- Fallback file storage if printing fails

## 🚀 Getting Started

### Prerequisites
- Python 3.7 or higher
- pip (Python package installer)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/Restaurant-POS.git
cd Restaurant-POS
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install required dependencies:
```bash
pip install -r requirements.txt
```

4. Run the application:
```bash
python app.py
```

5. Open your browser and navigate to `http://localhost:5000`

## 📁 Project Structure

```
Restaurant-POS/
├── app.py                 # Main Flask application & routes
├── restaurant.db          # SQLite database (auto-generated)
├── static/                # Static assets
│   ├── css/              # Stylesheets
│   │   └── style.css     # Main CSS file
│   ├── js/               # JavaScript files
│   │   └── script.js     # Client-side functionality
│   └── images/           # Image assets
├── templates/             # Jinja2 HTML templates
│   ├── base.html         # Base template (if exists)
│   ├── index.html        # Home page
│   ├── menu.html         # Menu display
│   └── order.html        # Order processing
├── requirements.txt       # Python dependencies
├── .gitignore            # Git ignore rules
└── README.md             # Project documentation
```

## 🔧 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Home page |
| `GET` | `/menu` | Display menu items |
| `POST` | `/order` | Process new orders |

## 🗄️ Database Schema

### Tables
- **orders**: Store complete orders with JSON item data, payment methods, customer names, and timestamps
- **promotions**: Configurable promotion system with buy-x-get-y logic and discount rules
- **users**: User authentication with username, password, and role-based access control