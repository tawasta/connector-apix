from odoo import SUPERUSER_ID, api


def init_apix_data(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["transmit.method"]._init_apix_transmit_methods()
