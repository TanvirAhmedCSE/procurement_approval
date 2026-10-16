from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    vendor_rating_ids = fields.One2many('vendor.rating', 'partner_id', string='Vendor Ratings')
    vendor_rating_count = fields.Integer(compute='_compute_vendor_rating', store=True)
    vendor_on_time_rate = fields.Float('On-time Delivery %', compute='_compute_vendor_rating', store=True)
    vendor_quality_avg = fields.Float('Avg. Quality (1-5)', compute='_compute_vendor_rating', store=True)
    vendor_score = fields.Float('Vendor Score (0-5)', compute='_compute_vendor_rating', store=True)

    @api.depends('vendor_rating_ids.on_time', 'vendor_rating_ids.quality_rating', 'vendor_rating_ids.score')
    def _compute_vendor_rating(self):
        for partner in self:
            ratings = partner.vendor_rating_ids
            partner.vendor_rating_count = len(ratings)
            if not ratings:
                partner.vendor_on_time_rate = partner.vendor_quality_avg = partner.vendor_score = 0.0
                continue
            rated = ratings.filtered('quality_rating')
            partner.vendor_on_time_rate = 100.0 * len(ratings.filtered('on_time')) / len(ratings)
            partner.vendor_quality_avg = (
                sum(int(r.quality_rating) for r in rated) / len(rated) if rated else 0.0)
            partner.vendor_score = sum(ratings.mapped('score')) / len(ratings)

    def action_view_vendor_ratings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Ratings'),
            'res_model': 'vendor.rating',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
        }
