from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProcurementBudget(models.Model):
    _name = 'procurement.budget'
    _description = 'Procurement Budget'
    _inherit = ['mail.thread']
    _order = 'date_from desc, id desc'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    budget_type = fields.Selection(
        [('department', 'Department'), ('project', 'Project')],
        required=True, default='department')
    department_id = fields.Many2one('hr.department')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Project (Analytic)')
    date_from = fields.Date(
        required=True, default=lambda self: fields.Date.today().replace(month=1, day=1))
    date_to = fields.Date(
        required=True, default=lambda self: fields.Date.today().replace(month=12, day=31))
    amount = fields.Monetary('Budget Limit', required=True, tracking=True)
    control = fields.Selection(
        [('block', 'Block confirmation'), ('warn', 'Warn only')],
        string='When Exceeded', required=True, default='block')
    committed = fields.Monetary('Committed', compute='_compute_usage')
    remaining = fields.Monetary('Remaining', compute='_compute_usage')
    used_percent = fields.Float('Used %', compute='_compute_usage')
    period_started = fields.Boolean(
        'Period Started', compute='_compute_period_started',
        search='_search_period_started')

    @api.depends('amount')
    def _compute_usage(self):
        data = {
            budget.id: total for budget, total in self.env['purchase.order'].sudo()._read_group(
                [('budget_id', 'in', self.ids), ('state', 'in', ('purchase', 'done'))],
                ['budget_id'], ['amount_total_company:sum'])
        }
        for budget in self:
            committed = data.get(budget.id, 0.0)
            budget.committed = committed
            budget.remaining = budget.amount - committed
            budget.used_percent = (committed / budget.amount * 100.0) if budget.amount else 0.0

    @api.depends('date_from')
    def _compute_period_started(self):
        today = fields.Date.context_today(self)
        for budget in self:
            budget.period_started = bool(budget.date_from) and budget.date_from <= today

    def _search_period_started(self, operator, value):
        if operator not in ('=', '!='):
            raise NotImplementedError(_("Unsupported search operator."))
        today = fields.Date.context_today(self)
        started = (operator == '=') == bool(value)
        return [('date_from', '<=' if started else '>', today)]

    @api.constrains('date_from', 'date_to', 'budget_type', 'department_id', 'analytic_account_id', 'amount')
    def _check_budget(self):
        for budget in self:
            if budget.date_from > budget.date_to:
                raise ValidationError(_("'Date From' must be before 'Date To'."))
            if budget.amount < 0:
                raise ValidationError(_("The budget limit cannot be negative."))
            if budget.budget_type == 'department' and not budget.department_id:
                raise ValidationError(_("Please select a department."))
            if budget.budget_type == 'project' and not budget.analytic_account_id:
                raise ValidationError(_("Please select a project."))