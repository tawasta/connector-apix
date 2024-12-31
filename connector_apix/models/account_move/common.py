import logging

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    date_einvoice_sent = fields.Date(string="eInvoice sent", copy=False)
    apix_bind_ids = fields.One2many(
        comodel_name="apix.account.invoice",
        inverse_name="odoo_id",
        string="APIX Bindings",
    )

    def get_apix_backend(self):
        self.ensure_one()

        if not self.company_id:
            raise ValidationError(_("This invoice has no company."))

        backend = self.env["apix.backend"].search(
            [
                ("company_id", "=", self.company_id.id),
            ],
            limit=1,
        )

        return backend
