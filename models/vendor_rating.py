from odoo import api, fields, models

QUALITY = [
    ('1', '1 - Very Poor'), ('2', '2 - Poor'), ('3', '3 - Average'),
    ('4', '4 - Good'), ('5', '5 - Excellent'),
]


class VendorRating(models.Model):
    """One record per validated vendor receipt."""
    _name = 'vendor.rating'
    _description = 'Vendor Delivery & Quality Rating'
    _order = 'date desc, id desc'

    partner_id = fields.Many2one('res.partner', string='Vendor', required=True, index=True)
    order_id = fields.Many2one('purchase.order', string='Purchase Order')
    picking_id = fields.Many2one('stock.picking', string='Receipt', ondelete='cascade')
    company_id = fields.Many2one(related='order_id.company_id', store=True)
    date = fields.Datetime('Received On')
    planned_date = fields.Datetime('Promised Date')
    delay_days = fields.Integer('Days Late')
    on_time = fields.Boolean('On Time')
    quality_rating = fields.Selection(QUALITY, string='Quality')
    delivery_score = fields.Float(compute='_compute_scores', store=True, digits=(3, 2))
    score = fields.Float('Score (0-5)', compute='_compute_scores', store=True, digits=(3, 2))

    @api.depends('on_time', 'delay_days', 'quality_rating')
    def _compute_scores(self):
        for rating in self:
            delivery = 5.0 if rating.on_time else max(0.0, 5.0 - rating.delay_days)
            rating.delivery_score = delivery
            if rating.quality_rating:
                rating.score = (delivery + int(rating.quality_rating)) / 2.0
            else:
                rating.score = delivery
