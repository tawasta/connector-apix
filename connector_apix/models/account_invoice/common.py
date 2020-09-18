# -*- coding: utf-8 -*-
import logging
import zipfile
import cStringIO
import base64

from odoo import fields, models, api
from odoo import _
from odoo.addons.queue_job.job import job
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ApixAccountInvoice(models.Model):
    # Binding Model for the APIX Invoice
    _name = 'apix.account.invoice'
    _inherit = 'apix.binding'
    _inherits = {'account.invoice': 'odoo_id'}
    _description = 'APIX Invoice'

    odoo_id = fields.Many2one(
        comodel_name='account.invoice',
        string='Invoice',
        required=True,
        ondelete='cascade'
    )

    _sql_constraints = [
        ('odoo_uniq', 'unique(backend_id, odoo_id)',
         'An APIX binding for this invoice already exists.'),
    ]


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    date_einvoice_sent = fields.Date(
        string='eInvoice sent',
        copy=False
    )

    apix_bind_ids = fields.One2many(
        comodel_name='apix.account.invoice',
        inverse_name='odoo_id',
        string='APIX Bindings',
    )

    @api.multi
    def get_apix_backend(self):
        self.ensure_one()

        if not self.company_id:
            raise ValidationError(_('This invoice has no company.'))

        backend = self.env['apix.backend'].search([
            ('company_id', '=', self.company_id.id),
        ], limit=1)

        return backend
