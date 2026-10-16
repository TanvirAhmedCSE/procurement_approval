from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    company_currency_id = fields.Many2one(related='company_id.currency_id', string='Company Currency')
    amount_total_company = fields.Monetary(
        'Total (Company Currency)', compute='_compute_amount_total_company',
        store=True, currency_field='company_currency_id')
    budget_id = fields.Many2one(
        'procurement.budget', string='Budget', copy=False, tracking=True,
        domain="[('company_id', '=', company_id)]")
    budget_remaining = fields.Monetary(
        related='budget_id.remaining', currency_field='company_currency_id')
    vendor_score = fields.Float(
        related='partner_id.commercial_partner_id.vendor_score', string='Vendor Score')

    approval_state = fields.Selection(
        [('none', 'Not Requested'), ('pending', 'Waiting Approval'),
         ('approved', 'Approved'), ('rejected', 'Rejected')],
        default='none', copy=False, tracking=True)
    approval_line_ids = fields.One2many('purchase.approval.line', 'order_id', copy=False)
    approval_amount = fields.Monetary(
        'Amount at Request', copy=False, currency_field='company_currency_id')
    requested_by_id = fields.Many2one('res.users', 'Requested By', copy=False)
    can_approve = fields.Boolean(compute='_compute_can_approve')

    
    # Computes
    
    @api.depends('amount_total', 'currency_id', 'company_id', 'date_order')
    def _compute_amount_total_company(self):
        for order in self:
            company = order.company_id
            if company and order.currency_id:
                date = (order.date_order or fields.Datetime.now()).date()
                order.amount_total_company = order.currency_id._convert(
                    order.amount_total, company.currency_id, company, date)
            else:
                order.amount_total_company = order.amount_total

    @api.depends('approval_state', 'approval_line_ids.state',
                 'approval_line_ids.approver_ids', 'requested_by_id')
    @api.depends_context('uid')
    def _compute_can_approve(self):
        user = self.env.user
        for order in self:
            line = order._get_current_approval_line()
            order.can_approve = bool(
                order.approval_state == 'pending' and line
                and user in line.approver_ids and user != order.requested_by_id)

    
    # Helpers
    
    def _get_required_rules(self):
        self.ensure_one()
        return self.env['procurement.approval.rule'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('min_amount', '<=', self.amount_total_company),
        ])

    def _get_current_approval_line(self):
        self.ensure_one()
        return self.approval_line_ids.filtered(lambda l: l.state == 'pending')[:1]

    def _approval_cleared(self):
        self.ensure_one()
        if not self._get_required_rules():
            return True
        return self.approval_state == 'approved' and self.amount_total_company <= self.approval_amount

    def _check_budget(self):
        for order in self.filtered('budget_id'):
            budget = order.budget_id
            order_date = (order.date_order or fields.Datetime.now()).date()
            if not budget.date_from <= order_date <= budget.date_to:
                raise UserError(_(
                    "Order date %(date)s is outside the period of budget '%(budget)s'.",
                    date=order_date, budget=budget.name))
            if order.amount_total_company > budget.remaining:
                msg = _(
                    "Budget '%(budget)s' exceeded: remaining %(remaining)s, this order %(amount)s.",
                    budget=budget.name, remaining=budget.remaining, amount=order.amount_total_company)
                if budget.control == 'block':
                    raise UserError(msg)
                order.message_post(body=msg)

    def _check_can_act(self):
        self.ensure_one()
        line = self._get_current_approval_line()
        user = self.env.user
        if self.approval_state != 'pending' or not line:
            raise UserError(_("This order is not waiting for approval."))
        if user not in line.approver_ids:
            raise UserError(_("You are not an approver for the current level (%s).", line.name))
        if user == self.requested_by_id:
            raise UserError(_("You cannot approve a purchase order that you requested yourself."))
        return line

    def _send_approval_mail(self, key, users, **ctx):
        """Uses the default outgoing mail server (Gmail SMTP)."""
        self.ensure_one()
        emails = {u.partner_id.email_formatted for u in users if u.partner_id.email}
        template = self.env.ref(
            'procurement_approval.mail_template_approval_%s' % key, raise_if_not_found=False)
        if not emails or not template:
            return
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        ctx['link'] = '%s/odoo/purchase.order/%s' % (base_url, self.id)
        template.sudo().with_context(**ctx).send_mail(
            self.id, force_send=True, email_values={'email_to': ','.join(emails)})

    def _request_approval(self):
        self.ensure_one()
        if self.approval_state == 'pending':
            raise UserError(_("This order is already waiting for approval."))
        rules = self._get_required_rules()
        self.approval_line_ids.sudo().unlink()
        lines = self.env['purchase.approval.line'].sudo().create([{
            'order_id': self.id,
            'sequence': index * 10,
            'name': rule.name,
            'rule_id': rule.id,
            'approver_ids': [(6, 0, rule.approver_ids.ids)],
        } for index, rule in enumerate(rules, 1)])
        self.write({
            'approval_state': 'pending',
            'approval_amount': self.amount_total_company,
            'requested_by_id': self.env.user.id,
        })
        self.message_post(body=_("Approval requested (%s level(s)).", len(lines)))
        first = lines[:1]
        self._send_approval_mail('request', first.approver_ids, level=first.name)

    
    # Confirm flow
    
    def button_confirm(self):
        to_confirm = self.env['purchase.order']
        for order in self:
            if order.state not in ('draft', 'sent'):
                to_confirm |= order
                continue
            order._check_budget()
            if order._approval_cleared():
                to_confirm |= order
            else:
                order._request_approval()
        if to_confirm:
            return super(PurchaseOrder, to_confirm).button_confirm()
        return True

    
    # Buttons
    
    def action_approval_approve(self):
        for order in self:
            line = order._check_can_act()
            if order.amount_total_company > order.approval_amount:
                raise UserError(_(
                    "The order total changed after approval was requested. "
                    "Cancel the approval request and submit it again."))
            line.write({
                'state': 'approved',
                'user_id': self.env.user.id,
                'date': fields.Datetime.now(),
            })
            order.message_post(body=_(
                "Level '%(level)s' approved by %(user)s.", level=line.name, user=self.env.user.name))
            nxt = order._get_current_approval_line()
            if nxt:
                order._send_approval_mail('request', nxt.approver_ids, level=nxt.name)
            else:
                order.approval_state = 'approved'
                order._send_approval_mail('approved', order.requested_by_id)
                order.button_confirm()
        return True

    def action_approval_reject(self):
        self.ensure_one()
        self._check_can_act()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Purchase Order'),
            'res_model': 'procurement.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def _do_reject(self, reason):
        self.ensure_one()
        line = self._check_can_act()
        line.write({
            'state': 'rejected',
            'user_id': self.env.user.id,
            'date': fields.Datetime.now(),
            'note': reason,
        })
        self.approval_state = 'rejected'
        self.message_post(body=_(
            "Rejected by %(user)s at level '%(level)s': %(reason)s",
            user=self.env.user.name, level=line.name, reason=reason))
        self._send_approval_mail('rejected', self.requested_by_id, level=line.name, reason=reason)

    def action_approval_reset(self):
        for order in self:
            if order.approval_state not in ('pending', 'rejected'):
                continue
            if order.state not in ('draft', 'sent'):
                raise UserError(_("Only draft orders can be reset."))
            order.approval_line_ids.sudo().unlink()
            order.approval_state = 'none'
            order.message_post(body=_("Approval request cancelled by %s.", self.env.user.name))
        return True
