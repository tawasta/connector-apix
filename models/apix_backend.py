# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ApixBackend(models.Model):
    _name = 'apix.backend'
    _description = 'APIX Backend'
    _inherit = 'connector.backend'

    company_id = fields.Many2one(
        comodel_name='res.company',
    )

    username = fields.Char(
        string='Username'
    )

    password = fields.Char(
        string='Password'
    )

    environment = fields.Selection(
        string='Environment',
        selection=[('test', 'Test'), ('production', 'Production')],
        default='test',
        required=True,
    )

    prefix = fields.Char(
        string='Prefix',
    )

    transfer_id = fields.Char(
        string='Transfer id',
    )

    transfer_key = fields.Char(
        string='Transfer id',
    )

    company_uuid = fields.Char(
        string='Transfer id',
    )