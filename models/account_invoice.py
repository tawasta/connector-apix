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
    def get_apix_backend(self):
        self.ensure_one()

        if not self.company_id:
            raise ValidationError(_('This invoice has no company.'))

        backend = self.env['apix.backend'].search([
            ('company_id', '=', self.company_id.id),
        ], limit=1)

        return backend

    @api.multi
    def get_apix_payload(self):
        self.ensure_one()

        _logger.debug("Generating APIX payload for '%s'" % self.name)

        file_name = 'finvoice_%s' % self.invoice_number
        xml_name = '%s.xml' % file_name
        pdf_name = '%s.pdf' % file_name

        # Get the PDF
        # TODO: configurable invoice template
        report_name = 'account.report_invoice'
        pdf = self.env['report'].get_pdf(self.ids, report_name)

        # Get attachments
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.invoice'),
            ('res_id', 'in', self.ids),
        ])

        in_memory_zip = cStringIO.StringIO()
        with zipfile.ZipFile(in_memory_zip, 'w') as payload_zip:

            # Wtite the XML-file to zip
            payload_zip.writestr(xml_name, self.finvoice_xml)

            # Write the PDF-file to zip (the attachment iteration should do this)
            # payload_zip.writestr(pdf_name, pdf)

            # Iterate through all the attachments
            for attachment in attachments:
                # Write the file to the cached zip
                file_name = attachment.name or 'attachment';
                payload_zip.writestr(file_name, base64.b64decode(attachment.datas))

        payload = in_memory_zip.getvalue()

        _logger.debug("APIX payload for '%s' generated" % self.name)

        return payload

    @api.multi
    @job
    def einvoice_send(self):
        for record in self:
            # Transmit method name
            transmit_method = record.transmit_method_id.name

            _logger.debug("Sending '%s' as '%s'" % (record.name, transmit_method))

            backend = record.get_apix_backend()

            if not backend:
                raise Exception(_("No backend found"))

            _logger.debug("Using backend %s" % backend.name)

            payload = record.get_apix_payload()

            # TODO: remove this
            # tmp_file = open('/tmp/apix_test_%s.zip' % self.invoice_number, 'w')
            # tmp_file.write(payload)
            # tmp_file.close()

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
        elif self.transmit_method_code in ['einvoice'] and not self.partner_id.vat:
            msg = _("Please set VAT number for the customer '%s' before sending an eInvoice.") \
                  % self.partner_id.name

        # Wrong invoice transmit type
        elif self.transmit_method_code not in ['einvoice', 'printing_service']:
            msg = _("This invoice has been marked to be sent manually.")

        elif not self.partner_bank_id:
            msg = _("Please define a bank account for the invoice.")

        else:
            result = True

        if msg:
            raise ValidationError(msg)

        return result
