import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class GrgAppLoginQrController(http.Controller):

    @http.route('/grg_app/qr/claim', type='http', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def claim(self, **kwargs):
        """Mobile app exchanges the one-time QR token for login details.

        Request  (header X-Odoo-Database: <odoo_db from QR>)
            POST /grg_app/qr/claim
            {"token": "...", "device_name": "Samsung A15"}

        Response 200
            {"ok": true, "data": {company_name, odoo_url, odoo_db, odoo_login,
                                  odoo_api_key, odoo_company_id}}
        Errors: 400 bad_request, 403 user_not_allowed, 404 invalid_token,
                409 already_used, 410 expired
        """
        try:
            body = json.loads(request.httprequest.get_data(as_text=True) or '{}')
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return request.make_json_response(
                {'ok': False, 'error': 'bad_request', 'message': 'Body must be a JSON object.'}, status=400)

        token = str(body.get('token') or '').strip()
        device_name = str(body.get('device_name') or '').strip()[:128]
        if not token or len(token) > 256:
            return request.make_json_response(
                {'ok': False, 'error': 'bad_request', 'message': 'Missing token.'}, status=400)

        ip = request.httprequest.remote_addr
        result, status = request.env['grg.app.login.qr.session'].sudo()._claim(token, device_name, ip)
        if not result.get('ok'):
            _logger.warning('App login QR claim rejected (%s) from %s', result.get('error'), ip)
        return request.make_json_response(result, status=status)
