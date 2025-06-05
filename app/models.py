from . import db
from werkzeug.security import generate_password_hash, check_password_hash

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    products = db.relationship('Product', backref='category', lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    price = db.Column(db.Float, default=0.0)         # Selling price
    cost_price = db.Column(db.Float, default=0.0)      # <-- Add this line
    barcode = db.Column(db.String(128), unique=True)  # <-- Add this line
    model_number = db.Column(db.String(128))  # Optional: add this line
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(16), default='user')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, server_default=db.func.now())
    total = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(32), nullable=True)
    items = db.relationship('SaleItem', backref='sale', lazy=True)

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    product = db.relationship('Product')

    @property
    def total(self):
        return self.price * self.quantity

class BusinessSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(128))
    business_address = db.Column(db.String(256))
    contact_number = db.Column(db.String(32))
    contact_email = db.Column(db.String(128))
    business_type = db.Column(db.String(64))