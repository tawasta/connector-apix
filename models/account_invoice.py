# -*- coding: utf-8 -*-
import logging
from odoo import fields, models, api
from odoo import _
from odoo.addons.queue_job.job import job
from odoo.exceptions import ValidationError

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
            record.validate_einvoice()

            # Add sending to queue
            record.with_delay().einvoice_send()

    @api.multi
    @job
    def einvoice_send(self):
        for record in self:
            # Transmit method name
            transmit_method = dict(
                self.fields_get(['invoice_transmit_method'])
                ['invoice_transmit_method']['selection'])[self.invoice_transmit_method]

            _logger.debug("Sending '%s' as '%s'" % (record.name, transmit_method))

            record.message_post(_('Invoice sent as "%s"') % transmit_method)
            _logger.debug("Sent '%s' as '%s'" % (record.name, transmit_method))

    @api.multi
    def validate_einvoice(self):
        result = False
        msg = False

        # Invoice can be sent only when it is open or paid
        # open: normal invoice
        # paid: for resending (original invoice is not received or not paid)
        if self.state not in ['open', 'paid']:
            msg = _("You can only send eInvoice if the invoice is open or paid")

        # VAT number is missing
        elif self.invoice_transmit_method in ['einvoice'] and not self.partner_id.vat:
            msg = _("Please set VAT number for the customer '%s' before sending an eInvoice.") \
                  % self.partner_id.name

        # Wrong invoice transmit type
        elif self.invoice_transmit_method not in ['einvoice', 'paper']:
            msg = _("This invoice has been marked to be sent manually.")

        elif not self.partner_bank_id:
            msg = _("Please define a bank account for the invoice.")

        else:
            result = True

        if msg:
            raise ValidationError(msg)

        return result
