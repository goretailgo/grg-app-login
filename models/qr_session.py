import base64
import datetime
import hashlib
import io
import json
import logging
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import qrcode
except ImportError:  # pragma: no cover
    qrcode = None

KEY_DURATIONS = [
    ('30', '1 Month'),
    ('90', '3 Months'),
    ('180', '6 Months'),
    ('365', '1 Year'),
    ('0', 'Persistent (no expiry)'),
]


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


class GrgAppLoginQrSession(models.Model):
    _name = 'grg.app.login.qr.session'
    _description = 'GRG App Login QR Session'
    _order = 'id desc'

    name = fields.Char(compute='_compute_name')
    state = fields.Selection([
        ('pending', 'Waiting for Scan'),
        ('scanned', 'Scanned'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
        ('revoked', 'Key Revoked'),
    ], default='pending', required=True, readonly=True, index=True)

    user_id = fields.Many2one('res.users', string='App User', required=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True)
    company_name = fields.Char(string='Company Name (in QR)', readonly=True)
    odoo_url = fields.Char(string='Odoo URL', readonly=True)
    odoo_db = fields.Char(string='Database', readonly=True)
    key_duration = fields.Selection(KEY_DURATIONS, string='API Key Validity', default='90', readonly=True)
    validity_seconds = fields.Integer(string='QR Validity (sec)', default=30, readonly=True)

    token_hash = fields.Char(readonly=True, index=True, copy=False, groups='base.group_system')
    expires_at = fields.Datetime(string='QR Expires At', readonly=True)
    qr_image = fields.Binary(string='QR Code', readonly=True, attachment=False, copy=False)

    scanned_at = fields.Datetime(readonly=True)
    device_name = fields.Char(readonly=True)
    scanned_ip = fields.Char(string='Scanned From IP', readonly=True)
    key_name = fields.Char(string='API Key Name', readonly=True)
    key_expiration = fields.Datetime(string='API Key Expires', readonly=True)

    def _compute_name(self):
        for rec in self:
            rec.name = 'QR #%s - %s' % (rec.id or '', rec.user_id.login or '')

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    @api.model
    def _new_session(self, vals):
        """Create a pending session with a fresh one-time token and its QR image."""
        if qrcode is None:
            raise UserError(_('Python library "qrcode" is not installed.'))
        token = secrets.token_urlsafe(32)
        validity = int(vals.get('validity_seconds') or 30)
        expires_at = fields.Datetime.now() + datetime.timedelta(seconds=validity)
        session = self.sudo().create(dict(
            vals,
            state='pending',
            token_hash=_hash_token(token),
            expires_at=expires_at,
            validity_seconds=validity,
        ))
        payload = {
            'type': 'grg_app_login',
            'v': 2,
            'company_name': session.company_name,
            'odoo_url': (session.odoo_url or '').rstrip('/'),
            'odoo_db': session.odoo_db,
            'token': token,
            'expires_at': int(expires_at.replace(tzinfo=datetime.timezone.utc).timestamp()),
        }
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
        qr.add_data(json.dumps(payload, separators=(',', ':')))
        qr.make(fit=True)
        buf = io.BytesIO()
        qr.make_image(fill_color='black', back_color='white').save(buf, format='PNG')
        session.qr_image = base64.b64encode(buf.getvalue())
        _logger.info('App login QR #%s created by %s for user %s (valid %ss)',
                     session.id, self.env.user.login, session.user_id.login, validity)
        return self.browse(session.id)

    # ------------------------------------------------------------------
    # Status (polled by the backend widget)
    # ------------------------------------------------------------------
    def _expire_if_needed(self):
        now = fields.Datetime.now()
        stale = self.filtered(lambda s: s.state == 'pending' and s.expires_at and s.expires_at <= now)
        if stale:
            stale.sudo().write({'state': 'expired', 'qr_image': False})

    def get_status(self):
        self.ensure_one()
        self._expire_if_needed()
        now = fields.Datetime.now()
        seconds_left = 0
        if self.state == 'pending' and self.expires_at:
            seconds_left = max(0, int((self.expires_at - now).total_seconds()))
        scanned_at = ''
        if self.scanned_at:
            scanned_at = fields.Datetime.context_timestamp(self, self.scanned_at).strftime('%d-%m-%Y %H:%M:%S')
        return {
            'id': self.id,
            'state': self.state,
            'seconds_left': seconds_left,
            'validity': self.validity_seconds or 30,
            'qr_url': '/web/image/%s/%s/qr_image?unique=%s' % (self._name, self.id, self.id),
            'scanned_at': scanned_at,
            'device_name': self.device_name or '',
            'scanned_ip': self.scanned_ip or '',
            'user_login': self.user_id.login,
            'company_name': self.company_name or '',
        }

    # ------------------------------------------------------------------
    # Claim (called by the mobile app through the controller, as sudo)
    # ------------------------------------------------------------------
    @api.model
    def _claim(self, token, device_name, ip):
        """Atomically consume a pending token and return login details.

        :returns: (response_dict, http_status)
        """
        token_hash = _hash_token(token)
        self.env.cr.execute("""
            UPDATE grg_app_login_qr_session
               SET state = 'scanned',
                   scanned_at = (now() AT TIME ZONE 'UTC'),
                   device_name = %s,
                   scanned_ip = %s,
                   qr_image = NULL
             WHERE token_hash = %s
               AND state = 'pending'
               AND expires_at > (now() AT TIME ZONE 'UTC')
         RETURNING id
        """, [device_name or None, ip or None, token_hash])
        row = self.env.cr.fetchone()
        self.invalidate_model()

        if not row:
            session = self.sudo().search([('token_hash', '=', token_hash)], limit=1)
            if not session:
                return {'ok': False, 'error': 'invalid_token', 'message': 'QR code is not valid.'}, 404
            if session.state == 'scanned':
                return {'ok': False, 'error': 'already_used', 'message': 'QR code was already scanned.'}, 409
            session._expire_if_needed()
            return {'ok': False, 'error': 'expired', 'message': 'QR code has expired. Generate a new one.'}, 410

        session = self.sudo().browse(row[0])
        user = session.user_id
        if not user.active or session.company_id not in user.company_ids:
            # roll back the claim: the whole request transaction is discarded on exception,
            # but we want a clean JSON error, so mark it cancelled instead.
            session.write({'state': 'cancelled'})
            return {'ok': False, 'error': 'user_not_allowed',
                    'message': 'User is inactive or has no access to this company.'}, 403

        days = int(session.key_duration or 0)
        key_expiration = (fields.Datetime.now() + datetime.timedelta(days=days)) if days else None
        key_name = 'GRG App QR #%s - %s - %s' % (session.id, user.login, (device_name or 'device')[:40])
        api_key = self.env['res.users.apikeys'].with_user(user).sudo()._generate(None, key_name, key_expiration)
        session.write({'key_name': key_name, 'key_expiration': key_expiration})

        _logger.info('App login QR #%s scanned by device "%s" from %s -> API key issued for %s',
                     session.id, device_name, ip, user.login)
        return {
            'ok': True,
            'data': {
                'company_name': session.company_name or session.company_id.name,
                'odoo_url': (session.odoo_url or '').rstrip('/'),
                'odoo_db': session.odoo_db,
                'odoo_login': user.login,
                'odoo_api_key': api_key,
                'odoo_company_id': session.company_id.id,
            },
        }, 200

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_cancel(self):
        self.filtered(lambda s: s.state == 'pending').write({'state': 'cancelled', 'qr_image': False})

    def action_revoke_key(self):
        for rec in self.filtered(lambda s: s.state == 'scanned' and s.key_name):
            keys = self.env['res.users.apikeys'].sudo().search([
                ('user_id', '=', rec.user_id.id), ('name', '=', rec.key_name)])
            keys._remove()
            rec.state = 'revoked'
        return True

    @api.autovacuum
    def _gc_expire_pending(self):
        self.search([('state', '=', 'pending'), ('expires_at', '<', fields.Datetime.now())]).write(
            {'state': 'expired', 'qr_image': False})
