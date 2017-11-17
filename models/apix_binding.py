# -*- coding: utf-8 -*-
from odoo import fields, models


class ApixBinding(models.AbstractModel):
    _name = 'apix.binding'
    _inherit = 'external.binding'
    _description = 'APIX Binding (abstract)'

    backend_id = fields.Many2one(
        comodel_name='apix.backend',
        string='Coffee Backend',
        required=True,
        ondelete='restrict',
    )

    accepted_document_id = fields.Integer(
        string='Accepted document id',
        index=True,
    )
