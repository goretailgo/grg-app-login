from odoo import _, api, fields, models
from odoo.addons.base.models.res_users import check_identity
from odoo.exceptions import UserError

from ..models.qr_session import KEY_DURATIONS


class GrgAppLoginQrWizard(models.TransientModel):
    _name = 'grg.app.login.qr.wizard'
    _description = 'GRG App Login QR Generator'

    state = fields.Selection(
        [('draft', 'Configure'), ('done', 'QR Ready')],
        default='draft', required=True)

    user_id = fields.Many2one(
        'res.users', string='App User', required=True,
        default=lambda self: self.env.user,
        domain=[('share', '=', False)],
        help='Internal user the mobile app will act as. An API key is issued for this user when the QR is scanned.')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    allowed_company_ids = fields.Many2many(
        'res.company', compute='_compute_allowed_company_ids')
    company_name = fields.Char(
        string='Company Name (in QR)', compute='_compute_company_name',
        store=True, readonly=False)
    odoo_url = fields.Char(
        string='Odoo URL', required=True,
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param('web.base.url'))
    odoo_db = fields.Char(
        string='Database', required=True,
        default=lambda self: self.env.cr.dbname)
    duration = fields.Selection(KEY_DURATIONS, string='API Key Validity', default='90', required=True)
    validity_seconds = fields.Integer(string='QR Valid For (sec)', default=30, required=True)

    session_id = fields.Many2one('grg.app.login.qr.session', readonly=True)
    session_ref = fields.Integer(readonly=True)

    @api.depends('user_id')
    def _compute_allowed_company_ids(self):
        for rec in self:
            rec.allowed_company_ids = rec.user_id.company_ids

    @api.depends('company_id')
    def _compute_company_name(self):
        for rec in self:
            rec.company_name = rec.company_id.name or ''

    @api.onchange('user_id')
    def _onchange_user_id(self):
        if self.user_id and self.company_id not in self.user_id.company_ids:
            self.company_id = self.user_id.company_id

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('App Login QR'),
        }

    def _create_session(self):
        self.ensure_one()
        if not self.env.user._is_system():
            raise UserError(_('Only Settings administrators can generate app login QR codes.'))
        if self.company_id not in self.user_id.company_ids:
            raise UserError(_('User %(user)s has no access to company %(company)s.',
                              user=self.user_id.name, company=self.company_id.name))
        if not 10 <= self.validity_seconds <= 600:
            raise UserError(_('QR validity must be between 10 and 600 seconds.'))
        if self.session_id:
            self.session_id.action_cancel()
        session = self.env['grg.app.login.qr.session']._new_session({
            'user_id': self.user_id.id,
            'company_id': self.company_id.id,
            'company_name': self.company_name or self.company_id.name,
            'odoo_url': (self.odoo_url or '').rstrip('/'),
            'odoo_db': self.odoo_db,
            'key_duration': self.duration,
            'validity_seconds': self.validity_seconds,
        })
        self.write({'state': 'done', 'session_id': session.id, 'session_ref': session.id})

    @check_identity
    def action_generate(self):
        self._create_session()
        return self._reopen()

    @check_identity
    def action_regenerate(self):
        self._create_session()
        return self._reopen()

    def action_done(self):
        if self.session_id:
            self.session_id.action_cancel()
        return {'type': 'ir.actions.act_window_close'}
