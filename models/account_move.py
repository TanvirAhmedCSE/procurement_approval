from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare

MATCH_GROUP = 'procurement_approval.group_proc_match_controller'


class AccountMove(models.Model):
    _inherit = 'account.move'

    match_state = fields.Selection(
        [('na', 'Not Applicable'), ('ok', 'Matched'), ('mismatch', 'Mismatch')],
        string='3-Way Match', compute='_compute_match_state', store=True)
    match_note = fields.Text('Mismatch Details', compute='_compute_match_state', store=True)
    match_override = fields.Boolean('Mismatch Accepted', copy=False, tracking=True)
    match_override_user_id = fields.Many2one('res.users', 'Accepted By', copy=False)

    @api.depends(
        'move_type', 'invoice_line_ids.display_type', 'invoice_line_ids.purchase_line_id',
        'invoice_line_ids.quantity', 'invoice_line_ids.price_unit',
        'invoice_line_ids.purchase_line_id.qty_received',
        'invoice_line_ids.purchase_line_id.qty_invoiced',
        'invoice_line_ids.purchase_line_id.product_qty',
        'invoice_line_ids.purchase_line_id.price_unit')
    def _compute_match_state(self):
        get_param = self.env['ir.config_parameter'].sudo().get_param
        price_tol = float(get_param('procurement_approval.price_tolerance', 0) or 0)
        qty_tol = float(get_param('procurement_approval.qty_tolerance', 0) or 0)
        qty_digits = self.env['decimal.precision'].precision_get('Product Unit')
        price_digits = self.env['decimal.precision'].precision_get('Product Price')
        for move in self:
            lines = move.invoice_line_ids.filtered(
                lambda l: l.display_type == 'product' and l.purchase_line_id)
            if move.move_type != 'in_invoice' or not lines:
                move.match_state = 'na'
                move.match_note = False
                continue
            notes = []
            for line in lines:
                pol = line.purchase_line_id
                ref = '%s / %s' % (pol.order_id.name, pol.product_id.display_name or pol.name)
                if float_compare(pol.qty_invoiced, pol.product_qty + qty_tol,
                                 precision_digits=qty_digits) > 0:
                    notes.append(_("%(ref)s: billed %(billed)s > ordered %(ordered)s",
                                   ref=ref, billed=pol.qty_invoiced, ordered=pol.product_qty))
                if pol.product_id.type == 'consu' and float_compare(
                        pol.qty_invoiced, pol.qty_received + qty_tol,
                        precision_digits=qty_digits) > 0:
                    notes.append(_("%(ref)s: billed %(billed)s > received %(received)s",
                                   ref=ref, billed=pol.qty_invoiced, received=pol.qty_received))
                if move.currency_id == pol.currency_id:
                    allowed = abs(pol.price_unit) * price_tol / 100.0
                    if float_compare(abs(line.price_unit - pol.price_unit), allowed,
                                     precision_digits=price_digits) > 0:
                        notes.append(_("%(ref)s: bill price %(bill)s != PO price %(po)s",
                                       ref=ref, bill=line.price_unit, po=pol.price_unit))
            move.match_state = 'mismatch' if notes else 'ok'
            move.match_note = '\n'.join(notes) if notes else False

    def _post(self, soft=True):
        block = self.env['ir.config_parameter'].sudo().get_param(
            'procurement_approval.block_mismatch', 'True')
        if block == 'True':
            blocked = self.filtered(lambda m: m.match_state == 'mismatch' and not m.match_override)
            if blocked:
                raise UserError(_(
                    "3-way match failed for: %(bills)s\n\n%(notes)s\n\n"
                    "Fix the bill, or ask a Match Controller to accept the mismatch.",
                    bills=', '.join(blocked.mapped(lambda m: m.name or m.ref or m.partner_id.name or str(m.id))),
                    notes='\n'.join(n for n in blocked.mapped('match_note') if n)))
        return super()._post(soft=soft)

    def action_match_accept(self):
        if not self.env.user.has_group(MATCH_GROUP):
            raise UserError(_("Only a Match Controller can accept a mismatch."))
        for move in self:
            move.write({'match_override': True, 'match_override_user_id': self.env.user.id})
            move.message_post(body=_("3-way match mismatch accepted by %s.", self.env.user.name))
        return True

    def action_match_revoke(self):
        if not self.env.user.has_group(MATCH_GROUP):
            raise UserError(_("Only a Match Controller can revoke this."))
        self.write({'match_override': False, 'match_override_user_id': False})
        return True
