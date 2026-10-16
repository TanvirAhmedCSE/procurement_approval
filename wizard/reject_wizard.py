from odoo import fields, models


class ProcurementRejectWizard(models.TransientModel):
    _name = 'procurement.reject.wizard'
    _description = 'Reject Purchase Order'

    order_id = fields.Many2one('purchase.order', required=True)
    reason = fields.Text(required=True)

    def action_reject(self):
        self.ensure_one()
        self.order_id._do_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
