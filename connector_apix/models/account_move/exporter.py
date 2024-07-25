import base64
import logging
import zipfile
from io import BytesIO

from lxml import etree

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_einvoice_send(self):
        for record in self:
            record.validate_einvoice()

            if len(self) > 1:
                # Add sending to queue
                job_desc = _("APIX send invoice '%s'") % record.number
                record.with_delay(description=job_desc).einvoice_send()
            else:
                # Send eInvoice now
                record.einvoice_send()

    def _get_finvoice_object(self):
        finvoice_object = super()._get_finvoice_object()

        self.add_finvoice_apix_fields(finvoice_object)

        return finvoice_object

    def _get_finvoice_message_sender_details(self):
        MessageSenderDetailsType = super()._get_finvoice_message_sender_details()
        MessageSenderDetailsType.set_FromIntermediator("APIX")

        return MessageSenderDetailsType

    def _get_finvoice_message_receiver_details(self):
        MessageReceiverDetailsType = super()._get_finvoice_message_receiver_details()

        if self.transmit_method_id.code == "printing_service":
            MessageReceiverDetailsType.set_ToIdentifier("TULOSTUS")

        return MessageReceiverDetailsType

    def add_finvoice_apix_fields(self, finvoice_object):
        # TODO: is this method used anymore?
        _logger.debug("Adding APIX fields to Finvoice")
        latest_invoice_pdf = self._get_latest_invoice_pdf()
        pdf_url = "file://%s" % latest_invoice_pdf.name

        # Get attachments
        attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "in", self.ids),
            ]
        )

        finvoice_object.set_InvoiceUrlNameText(["APIX_PDFFILE"])
        if attachments:
            finvoice_object.set_InvoiceUrlNameText(["APIX_ATTACHMENT"])

        finvoice_object.set_InvoiceUrlText([pdf_url])

        if attachments:
            finvoice_object.set_InvoiceUrlText(["attachment.zip"])

    def _add_attachments_to_finvoice(self, finvoice_string, add_zip=False):
        root = etree.fromstring(finvoice_string)

        new_element = etree.Element("InvoiceUrlNameText")
        new_element.text = "APIX_PDFFILE"
        root.append(new_element)

        if add_zip:
            new_element = etree.Element("InvoiceUrlNameText")
            new_element.text = "APIX_ATTACHMENT"
            root.append(new_element)

        new_element = etree.Element("InvoiceUrlText")
        new_element.text = "file://invoice.pdf"
        root.append(new_element)

        if add_zip:
            new_element = etree.Element("InvoiceUrlText")
            new_element.text = "file://attachment.zip"
            root.append(new_element)

        return etree.tostring(root)

    def get_apix_payload(self):
        self.ensure_one()

        _logger.debug(f"Generating APIX payload for '{self.name}'")
        # Generate PDF
        backend = self.get_apix_backend()

        # Get attachments
        attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "in", self.ids),
            ]
        )

        invoice_pdf = False
        # Generate invoice PDF if using custom template
        if backend.use_invoice_template and backend.invoice_template_id:
            report_name = backend.invoice_template_id.report_name
            inv_report = self.env["ir.actions.report"]._get_report_from_name(
                report_name
            )
            invoice_pdf = inv_report._render_qweb_pdf(self.ids)[0]

        # Finvoice XML / attachment
        finvoice_xml = self.edi_document_ids.filtered(
            lambda s: s.edi_format_id.code == "finvoice_3_0"
        )

        if not finvoice_xml:
            raise ValidationError(_("Could not find a Finvoice document to export"))

        finvoice_attachment = finvoice_xml.attachment_id

        in_memory_zip = BytesIO()
        in_memory_attachments_zip = BytesIO()
        with zipfile.ZipFile(in_memory_zip, "w") as payload_zip:
            if backend.use_attachments and attachments:
                with zipfile.ZipFile(in_memory_attachments_zip, "w") as attachment_zip:
                    # Iterate through all the attachments
                    for attachment in attachments:
                        file_name = attachment.name or "attachment"

                        # Write the file to the cached zip
                        datas = base64.b64decode(attachment.datas)
                        attachment_zip.writestr(file_name, datas)

                payload_zip.writestr(
                    "attachment.zip", in_memory_attachments_zip.getvalue()
                )

            finvoice_datas = base64.b64decode(finvoice_attachment.datas)

            if backend.use_invoice_template:
                add_zip = backend.use_attachments and len(attachments) > 0
                finvoice_datas = self._add_attachments_to_finvoice(
                    finvoice_datas, add_zip=add_zip
                )

            if invoice_pdf:
                payload_zip.writestr("invoice.pdf", invoice_pdf)

            payload_zip.writestr("invoice.xml", finvoice_datas)

        payload = in_memory_zip.getvalue()

        # Save payload for debugging purposes
        self.env["ir.attachment"].create(
            {
                "name": f"apix_payload_{self.name}.zip",
                "raw": payload,
            }
        )

        _logger.debug(f"APIX payload for '{self.name}' generated")

        return payload

    def einvoice_send(self):
        for record in self:
            # Transmit method name
            transmit_method = record.transmit_method_id.name

            _logger.debug(_(f"Sending '{record.name}' as '{transmit_method}'"))

            backend = record.get_apix_backend()

            if not backend:
                raise Exception(_("No backend found"))

            _logger.debug(f"Using backend {backend.name}")

            payload = record.get_apix_payload()

            try:
                response = backend.SendInvoiceZIP(payload)
            except ValidationError as error:
                raise error

            _logger.debug(_(f"Response for '{record.name}': {response}"))

            record.date_einvoice_sent = fields.Date.today()
            record.is_move_sent = True

            apix_batch_id = response.find(".//Value[@type='BatchID']")
            if apix_batch_id is not None:
                apix_batch_id = apix_batch_id.text

            apix_accepted_document_id = response.find(
                ".//Value[@type='AcceptedDocumentID']"
            )

            if apix_accepted_document_id is not None:
                apix_accepted_document_id = apix_accepted_document_id.text

            apix_cost_in_credits = response.find(".//Value[@type='CostInCredits']")

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
            self.sudo().env["apix.account.invoice"].create(binding_values)

            record.message_post(body=_(f"Invoice sent as '{transmit_method}'"))
            _logger.debug(_(f"Sent '{record.name}' as '{transmit_method}'"))

    def validate_einvoice(self):
        result = False
        msg = False

        # Invoice can be sent only when it is open or paid
        # open: normal invoice
        # paid: for resending (original invoice is not received or not paid)
        if self.state not in ["posted"]:
            msg = _("You can only send eInvoice after the invoice is posted")

        # Check these only for eInvoice
        elif self.transmit_method_code in ["einvoice"]:
            # VAT number is missing
            if not self.partner_id.vat:
                msg = (
                    _(
                        "Please set VAT number for the customer '%s' before "
                        "sending an eInvoice."
                    )
                    % self.partner_id.name
                )
            # Edicode is missing
            elif not self.partner_id.edicode:
                msg = (
                    _(
                        "Please set edicode for the customer '%s' "
                        "before sending an eInvoice."
                    )
                    % self.partner_id.name
                )
            # Operator is missing
            elif not self.partner_id.einvoice_operator_id:
                msg = (
                    _(
                        "Please set eInvoice operator for the customer '%s' "
                        "before sending an eInvoice."
                    )
                    % self.partner_id.name
                )

        # Wrong invoice transmit type
        elif self.transmit_method_code not in ["einvoice", "printing_service"]:
            msg = _("This invoice has been marked to be sent manually.")

        elif not self.partner_bank_id:
            msg = _("Please define a bank account for the invoice.")

        else:
            result = True

        if msg:
            raise ValidationError(msg)

        return result
