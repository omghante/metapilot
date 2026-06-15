"""
Template Classification Engine.

Classifies WhatsApp templates into industry, feature_group, and use_case
based on template name patterns, category, and component analysis.

Meta does NOT provide these classifications — we derive them internally.
"""
import re
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


# ========================================
# CLASSIFICATION RULES
# ========================================

# Pattern → (industry, feature_group, use_case)
# Patterns are matched against lowercase template name

CLASSIFICATION_RULES: list[Tuple[str, Dict[str, str]]] = [
    # ---- ORDER MANAGEMENT (E-commerce) ----
    (r'(order|purchase).*confirm', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Order confirmation'}),
    (r'(order|purchase).*cancel', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Order cancellation'}),
    (r'(order|purchase).*update', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Order update'}),
    (r'(order|purchase).*status', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Order status update'}),
    (r'(order|purchase).*refund', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Refund confirmation'}),
    (r'(order|purchase).*return', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Return confirmation'}),
    (r'(order|purchase).*track', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Order tracking'}),
    (r'refund', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Refund confirmation'}),

    # ---- DELIVERY / SHIPPING (E-commerce) ----
    (r'deliver', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Delivery update'}),
    (r'ship(ment|ping|ped)', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Shipping update'}),
    (r'dispatch', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Dispatch notification'}),
    (r'out.for.delivery', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Out for delivery'}),
    (r'track(ing)?', {'industry': 'E-commerce', 'feature_group': 'Order Management', 'use_case': 'Shipment tracking'}),

    # ---- CART / BROWSE (E-commerce / Marketing) ----
    (r'(abandon|cart).*(remind|recover)', {'industry': 'E-commerce', 'feature_group': 'Marketing', 'use_case': 'Cart abandonment'}),
    (r'cart', {'industry': 'E-commerce', 'feature_group': 'Marketing', 'use_case': 'Cart reminder'}),
    (r'(back.in.stock|restock)', {'industry': 'E-commerce', 'feature_group': 'Marketing', 'use_case': 'Back in stock alert'}),
    (r'(price.drop|discount|offer|sale|promo)', {'industry': 'E-commerce', 'feature_group': 'Marketing', 'use_case': 'Promotional offer'}),
    (r'(coupon|voucher|code)', {'industry': 'E-commerce', 'feature_group': 'Marketing', 'use_case': 'Coupon/Voucher'}),
    (r'(product|item).*recommend', {'industry': 'E-commerce', 'feature_group': 'Marketing', 'use_case': 'Product recommendation'}),
    (r'wishlist', {'industry': 'E-commerce', 'feature_group': 'Marketing', 'use_case': 'Wishlist reminder'}),

    # ---- PAYMENTS (Financial Services) ----
    (r'payment.*confirm', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Payment confirmation'}),
    (r'payment.*(due|remind|overdue)', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Payment due reminder'}),
    (r'payment.*(fail|decline|reject)', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Payment failure'}),
    (r'payment.*success', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Payment success'}),
    (r'payment.*receiv', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Payment received'}),
    (r'invoice', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Invoice notification'}),
    (r'bill(ing)?', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Billing update'}),
    (r'transaction', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Transaction alert'}),
    (r'(low.balance|insufficient)', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Low balance warning'}),
    (r'(receipt|pay)', {'industry': 'Financial Services', 'feature_group': 'Payments', 'use_case': 'Payment notification'}),

    # ---- ACCOUNT UPDATES ----
    (r'(account|acc).*(creat|register|signup|sign.up)', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Account creation confirmation'}),
    (r'(account|acc).*verif', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Account verification'}),
    (r'(account|acc).*activ', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Account activation'}),
    (r'(account|acc).*deactiv', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Account deactivation'}),
    (r'(account|acc).*cancel', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Cancellation confirmation'}),
    (r'(account|acc).*suspend', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Account suspension'}),
    (r'(account|acc).*update', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Account update'}),
    (r'password.*(reset|change|forgot)', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Password reset'}),
    (r'(renewal|renew|subscri)', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Renewal reminder'}),
    (r'(welcome|onboard)', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Welcome message'}),
    (r'verif(y|ication)', {'industry': 'General', 'feature_group': 'Account Updates', 'use_case': 'Verification'}),

    # ---- AUTHENTICATION ----
    (r'(otp|one.time|2fa|two.factor|mfa|auth.*code)', {'industry': 'General', 'feature_group': 'Authentication', 'use_case': 'OTP/2FA code'}),
    (r'(login|sign.in).*alert', {'industry': 'General', 'feature_group': 'Authentication', 'use_case': 'Login alert'}),
    (r'(security|suspicious)', {'industry': 'General', 'feature_group': 'Authentication', 'use_case': 'Security alert'}),

    # ---- EVENT & APPOINTMENT ----
    (r'appointment.*(remind|confirm|book|schedul)', {'industry': 'Healthcare', 'feature_group': 'Event Reminder', 'use_case': 'Appointment reminder'}),
    (r'appointment.*(cancel|reschedul)', {'industry': 'Healthcare', 'feature_group': 'Event Reminder', 'use_case': 'Appointment cancellation'}),
    (r'(event|webinar|seminar|workshop).*(remind|confirm|register|rsvp)', {'industry': 'General', 'feature_group': 'Event Reminder', 'use_case': 'Event RSVP confirmation'}),
    (r'(event|webinar|seminar|workshop)', {'industry': 'General', 'feature_group': 'Event Reminder', 'use_case': 'Event notification'}),
    (r'(remind|reminder)', {'industry': 'General', 'feature_group': 'Event Reminder', 'use_case': 'General reminder'}),
    (r'(booking|reserv)', {'industry': 'General', 'feature_group': 'Event Reminder', 'use_case': 'Booking confirmation'}),

    # ---- FEEDBACK & SUPPORT ----
    (r'(feedback|review|rating|survey)', {'industry': 'General', 'feature_group': 'Feedback', 'use_case': 'Feedback request'}),
    (r'(support|ticket|helpdesk|case)', {'industry': 'General', 'feature_group': 'Customer Support', 'use_case': 'Support ticket update'}),
    (r'(complaint|issue|problem)', {'industry': 'General', 'feature_group': 'Customer Support', 'use_case': 'Issue resolution'}),

    # ---- TELECOM ----
    (r'(recharge|top.up|data.pack|plan)', {'industry': 'Telecommunication', 'feature_group': 'Account Updates', 'use_case': 'Recharge/Plan update'}),
    (r'(usage|data.usage|call.usage)', {'industry': 'Telecommunication', 'feature_group': 'Account Updates', 'use_case': 'Usage alert'}),

    # ---- HEALTHCARE ----
    (r'(prescription|medicine|pharmacy|lab.report|test.result|health)', {'industry': 'Healthcare', 'feature_group': 'Healthcare', 'use_case': 'Health notification'}),
    (r'(doctor|physician|clinic|hospital)', {'industry': 'Healthcare', 'feature_group': 'Healthcare', 'use_case': 'Healthcare update'}),

    # ---- EDUCATION ----
    (r'(admission|enrollment|exam|result|grade|school|college|university|course)', {'industry': 'Education', 'feature_group': 'Education', 'use_case': 'Education update'}),

    # ---- MARKETING (general) ----
    (r'(newsletter|update|news|announcement)', {'industry': 'General', 'feature_group': 'Marketing', 'use_case': 'Newsletter/Update'}),
    (r'(campaign|promo|marketing|launch)', {'industry': 'General', 'feature_group': 'Marketing', 'use_case': 'Campaign message'}),
    (r'(thank|thanks|gratitude)', {'industry': 'General', 'feature_group': 'Marketing', 'use_case': 'Thank you message'}),
    (r'(greeting|wish|festival|holiday|diwali|christmas|eid|new.year)', {'industry': 'General', 'feature_group': 'Marketing', 'use_case': 'Seasonal greeting'}),

    # ---- NOTIFICATION (general) ----
    (r'(alert|notify|notification)', {'industry': 'General', 'feature_group': 'Notifications', 'use_case': 'General alert'}),
]

# Category-based defaults (fallback)
CATEGORY_DEFAULTS = {
    'UTILITY': {'industry': 'General', 'feature_group': 'Notifications', 'use_case': 'Utility notification'},
    'MARKETING': {'industry': 'General', 'feature_group': 'Marketing', 'use_case': 'Marketing message'},
    'AUTHENTICATION': {'industry': 'General', 'feature_group': 'Authentication', 'use_case': 'Authentication code'},
}


def classify_template(name: str, category: str = '', body_text: str = '') -> Dict[str, str]:
    """
    Classify a template based on its name, category, and body text.
    
    Returns dict with: industry, feature_group, use_case
    """
    # Combine name and body for matching
    search_text = f"{name} {body_text}".lower().strip()
    
    for pattern, classification in CLASSIFICATION_RULES:
        if re.search(pattern, search_text):
            return classification.copy()
    
    # Fallback to category defaults
    return CATEGORY_DEFAULTS.get(category, {
        'industry': 'General',
        'feature_group': 'Other',
        'use_case': 'General message',
    }).copy()


def extract_template_metadata(components: list) -> Dict:
    """
    Extract metadata from template components for fast filtering.
    
    Returns: has_header, header_format, has_buttons, button_count, body_text
    """
    result = {
        'has_header': False,
        'header_format': '',
        'has_buttons': False,
        'button_count': 0,
        'body_text': '',
    }
    
    for comp in (components or []):
        comp_type = comp.get('type', '').upper()
        
        if comp_type == 'HEADER':
            result['has_header'] = True
            result['header_format'] = comp.get('format', '').upper()
        
        elif comp_type == 'BODY':
            result['body_text'] = comp.get('text', '')
        
        elif comp_type == 'BUTTONS':
            buttons = comp.get('buttons', [])
            result['has_buttons'] = len(buttons) > 0
            result['button_count'] = len(buttons)
    
    return result
