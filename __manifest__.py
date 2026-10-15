{
    'name': 'GRG App Login QR',
    'version': '19.0.2.0.0',
    'summary': 'Short-lived (30s) one-time QR login for the GoRetailGo mobile app, with scan acknowledgement',
    'category': 'Tools',
    'author': 'GoRetailGo',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'external_dependencies': {'python': ['qrcode']},
    'data': [
        'security/ir.model.access.csv',
        'views/qr_session_views.xml',
        'wizard/app_login_qr_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'grg_app_login_qr/static/src/qr_session_field.js',
            'grg_app_login_qr/static/src/qr_session_field.xml',
        ],
    },
    'installable': True,
    'application': False,
}
