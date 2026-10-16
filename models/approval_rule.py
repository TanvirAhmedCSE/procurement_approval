from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProcurementApprovalRule(models.Model):
    """One approval level. A PO needs approval from EVERY level whose
    'min_amount' is <= the PO total (company currency), lowest level first."""
    _name = 'procurement.approval.rule'
    _description = 'Purchase Approval Level'
    _order = 'company_id, min_amount, id'

    name = fields.Char('Level Name', required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    min_amount = fields.Monetary(
        'Required From Amount', required=True, currency_field='currency_id',
        help="This level is required when the PO total (company currency) is at or above this amount.")
    approver_ids = fields.Many2many(
        'res.users', 'procurement_approval_rule_user_rel', 'rule_id', 'user_id',
        string='Approvers', required=True, domain="[('share', '=', False)]")

    @api.constrains('min_amount')
    def _check_min_amount(self):
        if any(rule.min_amount < 0 for rule in self):
            raise ValidationError(_("The amount cannot be negative."))


class PurchaseApprovalLine(models.Model):
    _name = 'purchase.approval.line'
    _description = 'Purchase Order Approval Step'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('purchase.order', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='order_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    name = fields.Char('Level', required=True)
    rule_id = fields.Many2one('procurement.approval.rule', ondelete='set null')
    approver_ids = fields.Many2many(
        'res.users', 'purchase_approval_line_user_rel', 'line_id', 'user_id', string='Approvers')
    state = fields.Selection(
        [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
        default='pending', required=True)
    user_id = fields.Many2one('res.users', string='Decided By')
    date = fields.Datetime('Decision Date')
    note = fields.Char('Reason')
