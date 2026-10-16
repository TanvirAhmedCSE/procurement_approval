import pytz

from odoo import fields, models

from .vendor_rating import QUALITY


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    quality_rating = fields.Selection(QUALITY, string='Received Quality', copy=False)

    def _action_done(self):
        res = super()._action_done()
        self._create_vendor_ratings()
        return res

    def write(self, vals):
        res = super().write(vals)
        if 'quality_rating' in vals:
            ratings = self.env['vendor.rating'].sudo().search([('picking_id', 'in', self.ids)])
            ratings.write({'quality_rating': vals['quality_rating']})
        return res

    def _local_date(self, dt):
        """Calendar date of a (naive, UTC) datetime in the user's timezone, so
        'late' follows the dates people actually see on screen."""
        self.ensure_one()
        tz_name = (
            self.env.context.get('tz')
            or self.env.user.tz
            or self.company_id.partner_id.tz
            or 'UTC'
        )
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            tz = pytz.utc
        return pytz.utc.localize(dt).astimezone(tz).date()

    def _create_vendor_ratings(self):
        Rating = self.env['vendor.rating'].sudo()
        for picking in self.filtered(
                lambda p: p.state == 'done' and p.picking_type_code == 'incoming'
                and p.purchase_id and p.partner_id):
            if Rating.search_count([('picking_id', '=', picking.id)]):
                continue
            order = picking.purchase_id.sudo()
            done = picking.date_done or fields.Datetime.now()
            planned = order.date_planned or picking.scheduled_date
            delay = (
                (picking._local_date(done) - picking._local_date(planned)).days
                if planned else 0)
            Rating.create({
                'partner_id': picking.partner_id.commercial_partner_id.id,
                'order_id': order.id,
                'picking_id': picking.id,
                'date': done,
                'planned_date': planned,
                'delay_days': max(delay, 0),
                'on_time': delay <= 0,
                'quality_rating': picking.quality_rating,
            })