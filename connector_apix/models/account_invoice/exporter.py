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

    @api.multi
    def action_einvoice_send(self):
        for record in self:
            record.validate_einvoice()

            # Add sending to queue
            # job_desc = _("APIX send invoice '%s'") % record.number
            # record.with_delay(description=job_desc).einvoice_send()

            # Send eInvoice now
            record.einvoice_send()

    def _get_finvoice_object(self):
        finvoice_object = super(AccountInvoice, self)._get_finvoice_object()

        self.add_finvoice_apix_fields(finvoice_object)

        return finvoice_object

    def _get_finvoice_message_sender_details(self):
        MessageSenderDetailsType = \
            super(AccountInvoice, self)._get_finvoice_message_sender_details()
        MessageSenderDetailsType.set_FromIntermediator('APIX')

        return MessageSenderDetailsType

    def _get_finvoice_message_receiver_details(self):
        MessageReceiverDetailsType = \
            super(AccountInvoice, self)._get_finvoice_message_receiver_details()

        if self.transmit_method_id.code == 'printing_service':
            MessageReceiverDetailsType.set_ToIdentifier('TULOSTUS')

        return MessageReceiverDetailsType

    def add_finvoice_apix_fields(self, finvoice_object):
        latest_invoice_pdf = self._get_latest_invoice_pdf()
        pdf_url = 'file://%s' % latest_invoice_pdf.name

        finvoice_object.set_InvoiceUrlNameText(['APIX_PDFFILE'])
        finvoice_object.set_InvoiceUrlText([pdf_url])

    def _get_latest_invoice_pdf(self):
        # Get latest invoice pdf attachment
        # TODO: this is far from being 100% reliable,
        #  as it only gets the latest pdf-attachment

        attachment_model = self.env['ir.attachment']
        search_domain = list()

        search_domain.append(('res_id', '=', self.id))
        search_domain.append(('res_model', '=', self._name))
        search_domain.append(('mimetype', '=', 'application/pdf'))

        # TODO: tag attachments as invoice pdf:s
        '''
        if hasattr(attachment_model, 'tag_field'):
            search_domain.append(('tag_field', '=', 'correct_tag'))
        '''

        attachment = attachment_model.search(
            search_domain, order='id DESC', limit=1
        )

        return attachment

    @api.multi
    def get_apix_payload(self):
        self.ensure_one()

        _logger.debug("Generating APIX payload for '%s'" % self.invoice_number)

        file_name = 'finvoice_%s' % self.invoice_number
        xml_name = '%s.xml' % file_name

        # Generate PDF
        backend = self.get_apix_backend()
        report_name = backend.invoice_template_id.report_name
        self.env['report'].with_context(
            type='binary',
            default_type='binary').get_pdf(self.ids, report_name)

        # Get attachments
        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.invoice'),
            ('res_id', 'in', self.ids),
        ])

        in_memory_zip = cStringIO.StringIO()
        with zipfile.ZipFile(in_memory_zip, 'w') as payload_zip:

            finvoice_xml = self.get_finvoice_xml('ISO-8859-15')
            if self.european_standard:
                # A hack to add SpecificationIdentifier to the XML. Finvoice-module will handle in later module versions
                finvoice_xml = finvoice_xml.replace("</MessageTimeStamp>", "</MessageTimeStamp><SpecificationIdentifier>EN16931</SpecificationIdentifier>")

            # Write the XML-file to zip
            payload_zip.writestr(
                xml_name, finvoice_xml)

            # Iterate through all the attachments
            for attachment in attachments:
                # Write the file to the cached zip
                file_name = attachment.name or 'attachment';
                payload_zip.writestr(
                    file_name,
                    base64.b64decode(attachment.datas)
                )

        payload = in_memory_zip.getvalue()

        _logger.debug("APIX payload for '%s' generated" % self.invoice_number)

        return payload

    @api.multi
    @job
    def einvoice_send(self):
        for record in self:
            # Transmit method name
            transmit_method = record.transmit_method_id.name

            _logger.debug(_("Sending '%s' as '%s'") %
                          (record.invoice_number, transmit_method))

            backend = record.get_apix_backend()

            if not backend:
                raise Exception(_("No backend found"))

            _logger.debug("Using backend %s" % backend.name)

            payload = record.get_apix_payload()

            # TODO: remove this
            # tmp_file = open('/tmp/apix_test_%s.zip' % record.invoice_number, 'w')
            # tmp_file.write(payload)
            # tmp_file.close()

            try:
                response = backend.SendInvoiceZIP(payload)
            except ValidationError as error:
                raise error

            _logger.debug(_("Response for '%s': %s") %
                          (record.invoice_number, response))

            record.date_einvoice_sent = fields.Date.today()
            record.sent = True

            apix_batch_id = response.find(".//Value[@type='BatchID']")
            if apix_batch_id is not None:
                apix_batch_id = apix_batch_id.text

            apix_accepted_document_id = response.find(
                ".//Value[@type='AcceptedDocumentID']")

            if apix_accepted_document_id is not None:
                apix_accepted_document_id = apix_accepted_document_id.text

            apix_cost_in_credits = response.find(
                ".//Value[@type='CostInCredits']")

            if apix_cost_in_credits is not None:
                apix_cost_in_credits = apix_cost_in_credits.text

            response.find(".//Value[@type='BatchID']").text

            binding_values = dict(
                backend_id=backend.id,
                odoo_id=record.id,
                apix_batch_id=apix_batch_id,
                apix_accepted_document_id=apix_accepted_document_id,
                apix_cost_in_credits=apix_cost_in_credits,
            )

            # Create a binding
            self.sudo().env['apix.account.invoice'].create(
                binding_values
            )

            record.message_post(_('Invoice sent as "%s"') % transmit_method)
            _logger.debug(_("Sent '%s' as '%s'") %
                          (record.invoice_number, transmit_method))

    @api.multi
    def validate_einvoice(self):
        result = False
        msg = False

        # Invoice can be sent only when it is open or paid
        # open: normal invoice
        # paid: for resending (original invoice is not received or not paid)
        if self.state not in ['open', 'paid']:
            msg = _("You can only send eInvoice if the invoice is open or paid")

        # Check these only for eInvoice
        elif self.transmit_method_code in ['einvoice']:
            # VAT number is missing
            if not self.partner_id.vat:
                msg = _("Please set VAT number for the customer '%s' before "
                        "sending an eInvoice.") % self.partner_id.name
            # Edicode is missing
            elif not self.partner_id.edicode:
                msg = _("Please set edicode for the customer '%s' "
                        "before sending an eInvoice.") % self.partner_id.name
            # Operator is missing
            elif not self.partner_id.einvoice_operator:
                msg = _("Please set eInvoice operator for the customer '%s' "
                        "before sending an eInvoice.") % self.partner_id.name

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
