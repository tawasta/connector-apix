# -*- coding: utf-8 -*-
from odoo import fields, models, api
#from odoo.addons.connector.queue.job import job


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
            # TODO: ivoice transmit type check
            record.apix_send_invoice()

    @api.multi
    #@job
    def apix_send_invoice(self):
        # Sends the invoice to APIX

        # Jobs should be created for one invoice at the time
        self.ensure_one()

        print self.finvoice_xml
