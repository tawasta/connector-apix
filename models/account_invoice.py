# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.addons.queue_job.job import job
import logging
_logger = logging.getLogger(__name__)


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    date_einvoice_sent = fields.Date(
        string='eInvoice sent',
        readonly=True,
        copy=False
    )

    @api.multi
    def action_einvoice_send(self):
        for record in self:
            # Send without delay so the user will get the error immediately
            record.einvoice_send()

    @api.multi
    @job
    def einvoice_send(self):
        for record in self:
            _logger.info("Sending '%s' as einvoice" % record.name)
