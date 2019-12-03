# -*- coding: utf-8 -*-
# Copyright 2016 Sunflower IT <http://sunflowerweb.nl>
# Copyright 2019 Coop IT Easy SCRLfs
#   - Vincent Van Rossem <vincent@coopiteasy.be>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from datetime import datetime, timedelta

from openerp import models, fields, api, _
from openerp.exceptions import Warning as UserError


class HrHolidays(models.Model):
    """Update analytic lines on status change of Leave Request"""

    _inherit = "hr.holidays"

    analytic_line_ids = fields.One2many(
        "account.analytic.line", "leave_id", "Analytic Lines"
    )

    @api.multi
    def add_timesheet_line(self, description, date, hours, account):
        """Add a timesheet line for this leave"""
        self.ensure_one()
        # User exists because already check during the holidays_validate
        user = self.employee_id.user_id
        self.sudo().with_context(force_write=True).write(
            {
                "analytic_line_ids": [
                    (
                        0,
                        False,
                        {
                            "name": description,
                            "date": date,
                            "unit_amount": hours,
                            "company_id": self.employee_id.company_id.id,
                            "account_id": account.id,
                            "user_id": user.id,
                            "is_timesheet": True,
                        },
                    )
                ]
            }
        )

    @api.model
    def _get_company_hours_per_day(self, company):
        hours_per_day = company.timesheet_hours_per_day
        if not hours_per_day:
            raise UserError(
                _("No hours per day defined for Company '%s'")
                % (company.name,)
            )
        return hours_per_day

    @api.model
    def _get_contract_hours_per_day(self, employee, date):
        hours_per_day = 0.0
        contracts = (
            self.env["hr.contract"]
            .sudo()
            .search([("employee_id.id", "=", employee.id)])
        )
        for contract in contracts:
            for calendar in contract.working_hours:
                for wh in calendar.get_working_hours_of_date(start_dt=date):
                    hours_per_day += wh
        return hours_per_day

    @api.multi
    def holidays_validate(self):
        """On grant of leave, add timesheet lines"""
        res = super(HrHolidays, self).holidays_validate()

        # Postprocess Leave Types that have an analytic account configured
        for leave in self:
            account = leave.holiday_status_id.analytic_account_id
            if (
                not account
                or leave.type != "remove"
                or leave.analytic_line_ids
            ):
                # we only work on leaves (type=remove, type=add is allocation)
                # which have an account set and dont yet point to a leave
                continue

            # Assert hours per working day
            employee = leave.employee_id
            company = employee.company_id

            # Assert user connected to employee
            user = leave.employee_id.user_id
            if not user:
                raise UserError(
                    _("No user defined for Employee '%s'")
                    % (leave.employee_id.name,)
                )

            # Add analytic lines for these leave hours
            dt_from = fields.Datetime.from_string(leave.date_from)
            for day in range(abs(int(leave.number_of_days))):
                dt_current = dt_from + timedelta(days=day)

                # Assert hours per working day
                if employee.contract_ids:
                    hours_per_day = self._get_contract_hours_per_day(
                        employee, dt_current
                    )
                else:
                    hours_per_day = self._get_company_hours_per_day(company)

                # Skip the days not covered by a contract
                if hours_per_day:
                    leave.add_timesheet_line(
                        description=leave.name or leave.holiday_status_id.name,
                        date=dt_current,
                        hours=hours_per_day,
                        account=account,
                    )

        return res

    @api.multi
    def holidays_refuse(self):
        """On refusal of leave, delete timesheet lines"""
        res = super(HrHolidays, self).holidays_refuse()
        self.mapped("analytic_line_ids").with_context(
            force_write=True
        ).unlink()
        return res
