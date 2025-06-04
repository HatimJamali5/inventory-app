import base64
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import random
import string
import json
import os
from flask import current_app
from werkzeug.utils import secure_filename
import qrcode
import io
from flask import send_file
from functools import wraps
from flask import abort
import pandas as pd

from .models import Product, Category, User, Sale, SaleItem, BusinessSettings
from . import db

main = Blueprint('main', __name__)

users = {'admin': 'password'}

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@main.route('/')
def home():
    if 'username' not in session:
        return redirect(url_for('main.login'))

    total_products = Product.query.count()
    total_categories = Category.query.count()
    total_stock = db.session.query(db.func.sum(Product.quantity)).scalar() or 0
    total_value = db.session.query(db.func.sum(Product.quantity * Product.price)).scalar() or 0.0

    # Top 5 products by quantity
    top_products = Product.query.order_by(Product.quantity.desc()).limit(5).all()

    return render_template(
        'dashboard.html',
        username=session['username'],
        total_products=total_products,
        total_categories=total_categories,
        total_stock=total_stock,
        total_value=total_value,
        top_products=top_products
    )

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash('Logged in successfully.')
            return redirect(url_for('main.home'))
        flash('Invalid credentials.')
    return render_template('login.html')

@main.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.login'))

@main.route('/products')
def view_products():
    search = request.args.get('search', '').strip()
    products_query = Product.query

    if search:
        products_query = products_query.join(Category, isouter=True).filter(
            (Product.name.ilike(f'%{search}%')) |
            (Category.name.ilike(f'%{search}%'))
        )
    products = products_query.all()
    total_value = sum(p.quantity * p.price for p in products)
    return render_template('products.html', products=products, total_value=total_value, search=search)

@main.route('/add_product', methods=['GET', 'POST'])
@admin_required
def add_product():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        model_number = request.form.get('model_number', '').strip()
        barcode = request.form.get('barcode', '').strip()
        # Auto-generate barcode if not provided
        if not barcode:
            barcode = model_number if model_number else name

        quantity = int(request.form['quantity'])
        price = float(request.form['price'])
        cost_price_raw = request.form.get('cost_price', '').strip()
        cost_price = float(cost_price_raw) if cost_price_raw else 0.0
        new_category = request.form.get('new_category', '').strip()
        category_id = request.form.get('category_id')

        if new_category:
            category = Category.query.filter_by(name=new_category).first()
            if not category:
                category = Category(name=new_category)
                db.session.add(category)
                db.session.commit()
            category_id = category.id
        elif category_id:
            category_id = int(category_id)
        else:
            category_id = None

        product = Product(
            name=name,
            model_number=model_number,
            barcode=barcode,
            quantity=quantity,
            price=price,
            cost_price=cost_price,
            category_id=category_id
        )
        db.session.add(product)
        db.session.commit()
        flash('Product added successfully!')
        return redirect(url_for('main.view_products'))
    categories = Category.query.all()
    return render_template('add_product.html', categories=categories)

@main.route('/delete_product/<int:id>')
@admin_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for('main.view_products'))

@main.route('/edit_product/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_product(id):
    product = Product.query.get_or_404(id)
    categories = Category.query.all()
    if request.method == 'POST':
        product.name = request.form['name']
        product.quantity = int(request.form['quantity'])
        product.price = float(request.form['price'])
        cost_price_raw = request.form.get('cost_price', '').strip()
        product.cost_price = float(cost_price_raw) if cost_price_raw else 0.0
        new_category = request.form.get('new_category', '').strip()
        category_id = request.form.get('category_id')

        if new_category:
            category = Category.query.filter_by(name=new_category).first()
            if not category:
                category = Category(name=new_category)
                db.session.add(category)
                db.session.commit()
            product.category_id = category.id
        elif category_id:
            product.category_id = int(category_id)
        else:
            product.category_id = None

        db.session.commit()
        return redirect(url_for('main.view_products'))
    return render_template('edit_product.html', product=product, categories=categories)

@main.route('/register', methods=['GET', 'POST'])
def register():
    # Allow registration if no users exist, else require admin
    if User.query.count() > 0 and session.get('role') != 'admin':
        flash('Only admin can register new users.')
        return redirect(url_for('main.login'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
            return redirect(url_for('main.register'))
        # First user is admin, others are users
        role = 'admin' if User.query.count() == 0 else 'user'
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.')
        return redirect(url_for('main.login'))
    return render_template('register.html')

@main.route('/pos', methods=['GET', 'POST'])
def pos():
    products = Product.query.all()
    if request.method == 'POST':
        cart_data = request.form.get('cart_data')
        discount_type = request.form.get('discount_type', 'amount')
        discount_value = float(request.form.get('discount_value', 0))
        if not cart_data:
            flash('No items selected.')
            return render_template('pos.html', products=products)
        cart = json.loads(cart_data)
        items = []
        subtotal = 0
        for item in cart:
            product = Product.query.get(item['id'])
            qty = int(item['quantity'])
            price = float(item['price'])
            if product and qty > 0 and qty <= product.quantity:
                total = qty * price
                items.append({'product': product, 'quantity': qty, 'price': price, 'total': total})
                subtotal += total
        # Calculate discount
        if discount_type == 'percent':
            discount = subtotal * (discount_value / 100)
        else:
            discount = discount_value
        grand_total = subtotal - discount
        if items:
            sale = Sale(total=grand_total)
            db.session.add(sale)
            db.session.commit()
            for item in items:
                sale_item = SaleItem(
                    sale_id=sale.id,
                    product_id=item['product'].id,
                    quantity=item['quantity'],
                    price=item['price']
                )
                item['product'].quantity -= item['quantity']
                db.session.add(sale_item)
            db.session.commit()
            # Generate QR code for invoice number
            qr = qrcode.make(f"Invoice #{sale.id}")
            buf = io.BytesIO()
            qr.save(buf, format='PNG')
            qr_b64 = base64.b64encode(buf.getvalue()).decode('ascii')
            settings = BusinessSettings.query.first()
            return render_template('bill.html', sale=sale, items=items, discount=discount, total=subtotal, settings=settings, qr_b64=qr_b64)
        else:
            flash('No valid items selected.')
    return render_template('pos.html', products=products)

@main.route('/sales_history')
def sales_history():
    sales = Sale.query.order_by(Sale.date.desc()).all()
    profits = []
    for sale in sales:
        profit = sum((item.price - (item.product.cost_price or 0)) * item.quantity for item in sale.items)
        profits.append(profit)
    return render_template('sales_history.html', sales=sales, profits=profits)

@main.route('/delete_sale/<int:sale_id>', methods=['POST'])
@admin_required
def delete_sale(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    # Restore product quantities
    for item in sale.items:
        item.product.quantity += item.quantity
    # Delete sale and its items
    for item in sale.items:
        db.session.delete(item)
    db.session.delete(sale)
    db.session.commit()
    flash('Invoice deleted and stock restored.')
    return redirect(url_for('main.sales_history'))

@main.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    settings = BusinessSettings.query.first()
    if not settings:
        settings = BusinessSettings(
            business_name='',
            business_address='',
            contact_number='',
            contact_email='',
            business_type=''
        )
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        settings.business_name = request.form.get('business_name', '')
        settings.business_address = request.form.get('business_address', '')
        settings.contact_number = request.form.get('contact_number', '')
        settings.contact_email = request.form.get('contact_email', '')
        settings.business_type = request.form.get('business_type', '')
        db.session.commit()
        flash('Settings updated successfully.')
        return redirect(url_for('main.settings'))

    return render_template('settings.html', settings=settings)

@main.route('/apply_discount', methods=['POST'])
def apply_discount():
    cart = session.get('cart', [])
    discount_type = request.form.get('discount_type', 'amount')
    discount_value = float(request.form.get('discount_value', 0))

    subtotal = sum(item['price'] * item['quantity'] for item in cart)
    if discount_type == 'percent':
        discount = subtotal * (discount_value / 100)
    else:
        discount = discount_value
    grand_total = subtotal - discount

    return render_template('cart.html', cart=cart, subtotal=subtotal, discount=discount, grand_total=grand_total)

@main.route('/product_detail/<int:id>', methods=['GET'])
def product_detail(id):
    product = Product.query.get_or_404(id)
    # Generate QR code for product
    qr = qrcode.make(f"Product: {product.name} (ID: {product.id})")
    buf = io.BytesIO()
    qr.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return render_template('product_detail.html', product=product, qr_b64=qr_b64)

@main.route('/print_label/<int:product_id>', methods=['GET', 'POST'])
def print_label(product_id):
    product = Product.query.get_or_404(product_id)
    settings = BusinessSettings.query.first()
    show_price = True
    custom_price = None
    if request.method == 'POST':
        show_price = request.form.get('show_price') == 'on'
        custom_price = request.form.get('custom_price')
        if custom_price:
            custom_price = custom_price.strip()
        else:
            custom_price = None

    # Generate QR code (or use barcode library for barcode)
    qr_data = product.barcode or product.model_number or product.name
    qr = qrcode.make(qr_data)
    buf = io.BytesIO()
    qr.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode('ascii')

    return render_template(
        'print_label.html',
        product=product,
        settings=settings,
        qr_b64=qr_b64,
        show_price=show_price,
        custom_price=custom_price
    )

@main.route('/sale_return/<int:sale_id>', methods=['GET', 'POST'])
def sale_return(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    items = SaleItem.query.filter_by(sale_id=sale.id).all()
    if request.method == 'POST':
        for item in items:
            qty_returned = int(request.form.get(f'return_qty_{item.id}', 0))
            if qty_returned > 0 and qty_returned <= item.quantity:
                product = Product.query.get(item.product_id)
                product.quantity += qty_returned
                item.quantity -= qty_returned
        db.session.commit()
        # Check if all items have quantity 0
        all_returned = all(item.quantity == 0 for item in items)
        if all_returned:
            # Delete all SaleItems and the Sale itself
            for item in items:
                db.session.delete(item)
            db.session.delete(sale)
            db.session.commit()
            flash('All products returned. Invoice removed from sales history.')
        else:
            flash('Sale return processed.')
        return redirect(url_for('main.sales_history'))
    return render_template('sale_return.html', sale=sale, items=items)

@main.route('/replace_product/<int:sale_id>', methods=['GET', 'POST'])
def replace_product(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    items = SaleItem.query.filter_by(sale_id=sale.id).all()
    products = Product.query.all()
    if request.method == 'POST':
        old_item_id = int(request.form['old_item_id'])
        new_product_id = int(request.form['new_product_id'])
        qty = int(request.form['replace_qty'])
        old_item = SaleItem.query.get(old_item_id)
        new_product = Product.query.get(new_product_id)
        if old_item and new_product and qty > 0 and qty <= old_item.quantity:
            # Return old product to stock
            old_item.product.quantity += qty
            old_item.quantity -= qty
            # Deduct new product from stock
            new_product.quantity -= qty
            # Add new SaleItem for replacement
            replacement = SaleItem(
                sale_id=sale.id,
                product_id=new_product.id,
                quantity=qty,
                price=new_product.price
            )
            db.session.add(replacement)
            db.session.commit()
            flash('Product replaced successfully.')
            return redirect(url_for('main.sales_history'))
    return render_template('replace_product.html', sale=sale, items=items, products=products)

@main.route('/admin_only')
@admin_required
def admin_only_view():
    return render_template('admin_panel.html')

@main.route('/user_management')
@admin_required
def user_management():
    users = User.query.all()
    return render_template('user_management.html', users=users)

@main.route('/promote_user/<int:user_id>', methods=['POST'])
@admin_required
def promote_user(user_id):
    user = User.query.get_or_404(user_id)
    user.role = 'admin'
    db.session.commit()
    flash(f'User {user.username} promoted to admin.')
    return redirect(url_for('main.user_management'))

@main.route('/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot delete an admin user.')
        return redirect(url_for('main.user_management'))
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} deleted.')
    return redirect(url_for('main.user_management'))

@main.route('/import_inventory', methods=['GET', 'POST'])
@admin_required
def import_inventory():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith(('.xlsx', '.xls')):
            flash('Please upload a valid Excel file.')
            return redirect(url_for('main.import_inventory'))
        filename = secure_filename(file.filename)
        filepath = os.path.join(current_app.root_path, 'uploads', filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file.save(filepath)
        errors = []
        imported = 0
        try:
            df = pd.read_excel(filepath)
            # Normalize column names (lowercase, no spaces)
            df.columns = [str(col).strip().lower().replace(' ', '_') for col in df.columns]
            for idx, row in df.iterrows():
                try:
                    name = str(row.get('name', '')).strip()
                    if not name:
                        errors.append(f"Row {idx+2}: Missing product name. Skipped.")
                        continue
                    quantity = int(row.get('quantity', 0)) if pd.notnull(row.get('quantity', 0)) else 0
                    price = float(row.get('price', 0)) if pd.notnull(row.get('price', 0)) else 0.0
                    cost_price = float(row.get('cost_price', 0)) if pd.notnull(row.get('cost_price', 0)) else 0.0
                    category_name = str(row.get('category', '')).strip() if pd.notnull(row.get('category', '')) else ''
                    # Find or create category
                    category = None
                    if category_name:
                        category = Category.query.filter_by(name=category_name).first()
                        if not category:
                            category = Category(name=category_name)
                            db.session.add(category)
                            db.session.commit()
                    # Find or create product
                    product = Product.query.filter_by(name=name).first()
                    if product:
                        product.quantity = quantity
                        product.price = price
                        product.cost_price = cost_price
                        product.category_id = category.id if category else None
                    else:
                        product = Product(
                            name=name,
                            quantity=quantity,
                            price=price,
                            cost_price=cost_price,
                            category_id=category.id if category else None
                        )
                        db.session.add(product)
                    imported += 1
                except Exception as row_e:
                    errors.append(f"Row {idx+2}: {row_e}")
            db.session.commit()
            msg = f"Imported {imported} products."
            if errors:
                msg += f" {len(errors)} issues:<br>" + "<br>".join(errors[:10])
                if len(errors) > 10:
                    msg += "<br>...and more."
            flash(msg)
        except Exception as e:
            flash(f'Error importing inventory: {e}')
        finally:
            os.remove(filepath)
        return redirect(url_for('main.view_products'))
    return render_template('import_inventory.html')

@main.route('/export_inventory')
@admin_required
def export_inventory():
    products = Product.query.all()
    data = []
    for p in products:
        data.append({
            'id': p.id,
            'name': p.name,
            'quantity': p.quantity,
            'price': p.price,
            'cost_price': p.cost_price,
            'barcode': p.barcode,
            'model_number': p.model_number,
            'category': p.category.name if p.category else ''
        })
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Inventory')
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name='inventory_export.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@main.route('/product_barcode/<int:product_id>')
def product_barcode(product_id):
    product = Product.query.get_or_404(product_id)
    code_value = product.barcode or product.name or product.model_number or str(product.id)
    img = qrcode.make(code_value)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@main.app_errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403





