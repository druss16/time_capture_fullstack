from django.db import migrations


# All FK constraints referencing tracker_organization, with their exact names,
# child table, and column name.
CONSTRAINTS = [
    ("tracker_agenterror",          "tracker_agenterror_org_id_689937e7_fk_tracker_organization_id",      "org_id",          "tracker_organization"),
    ("tracker_agentregistration",   "tracker_agentregistr_org_id_714375ac_fk_tracker_o",                  "org_id",          "tracker_organization"),
    ("tracker_aiprocessinglog",     "tracker_aiprocessing_org_id_e009636d_fk_tracker_o",                  "org_id",          "tracker_organization"),
    ("tracker_aitrainingexample",   "tracker_aitrainingex_org_id_4720ffc1_fk_tracker_o",                  "org_id",          "tracker_organization"),
    ("tracker_billingrate",         "tracker_billingrate_org_id_c4b27860_fk_tracker_organization_id",     "org_id",          "tracker_organization"),
    ("tracker_block",               "tracker_block_org_id_ebf6ae94_fk_tracker_organization_id",           "org_id",          "tracker_organization"),
    ("tracker_client",              "tracker_client_org_id_05edf9b2_fk_tracker_organization_id",          "org_id",          "tracker_organization"),
    ("tracker_clientassignment",    "tracker_clientassign_organization_id_243983d4_fk_tracker_o",         "organization_id", "tracker_organization"),
    ("tracker_clientbudget",        "tracker_clientbudget_org_id_8ebf2119_fk_tracker_organization_id",    "org_id",          "tracker_organization"),
    ("tracker_clientgroup",         "tracker_clientgroup_org_id_9c5b5d94_fk_tracker_organization_id",     "org_id",          "tracker_organization"),
    ("tracker_clientpattern",       "tracker_clientpatter_org_id_72ab0a4c_fk_tracker_o",                  "org_id",          "tracker_organization"),
    ("tracker_clientrequest",       "tracker_clientreques_organization_id_53c84946_fk_tracker_o",         "organization_id", "tracker_organization"),
    ("tracker_deviceprovisioningmap","tracker_deviceprovis_organization_id_405fa96e_fk_tracker_o",        "organization_id", "tracker_organization"),
    ("tracker_employeecostrate",    "tracker_employeecost_organization_id_f07d55dc_fk_tracker_o",         "organization_id", "tracker_organization"),
    ("tracker_integration",         "tracker_integration_organization_id_05ee6951_fk_tracker_o",          "organization_id", "tracker_organization"),
    ("tracker_invitation",          "tracker_invitation_organization_id_76d6ecd5_fk_tracker_o",           "organization_id", "tracker_organization"),
    ("tracker_invoice",             "tracker_invoice_org_id_01ce69f5_fk_tracker_organization_id",         "org_id",          "tracker_organization"),
    ("tracker_invoiceconflict",     "tracker_invoiceconfl_org_id_b6ec7fe6_fk_tracker_o",                  "org_id",          "tracker_organization"),
    ("tracker_knownentity",         "tracker_knownentity_org_id_9eac08ea_fk_tracker_organization_id",     "org_id",          "tracker_organization"),
    ("tracker_onboardingbatch",     "tracker_onboardingba_organization_id_5de73065_fk_tracker_o",         "organization_id", "tracker_organization"),
    ("tracker_organizationsettings","tracker_organization_org_id_8b1ced9c_fk_tracker_o",                  "org_id",          "tracker_organization"),
    ("tracker_organizationmembership","tracker_organization_organization_id_acfe54df_fk_tracker_o",       "organization_id", "tracker_organization"),
    ("tracker_orgdeploymenttoken",  "tracker_orgdeploymen_organization_id_d92f749e_fk_tracker_o",         "organization_id", "tracker_organization"),
    ("tracker_orginstalltoken",     "tracker_orginstallto_org_id_243c75fb_fk_tracker_o",                  "org_id",          "tracker_organization"),
    ("tracker_orgprofile",          "tracker_orgprofile_org_id_220863f6_fk_tracker_organization_id",      "org_id",          "tracker_organization"),
    ("tracker_project",             "tracker_project_org_id_cc16e5ec_fk_tracker_organization_id",         "org_id",          "tracker_organization"),
    ("tracker_rule",                "tracker_rule_org_id_fddb5c04_fk_tracker_organization_id",            "org_id",          "tracker_organization"),
    ("tracker_task",                "tracker_task_org_id_56bc0b07_fk_tracker_organization_id",            "org_id",          "tracker_organization"),
    ("tracker_taskpattern",         "tracker_taskpattern_org_id_17e05b79_fk_tracker_organization_id",     "org_id",          "tracker_organization"),
    ("tracker_tasktype",            "tracker_tasktype_org_id_5f472e47_fk_tracker_organization_id",        "org_id",          "tracker_organization"),
    ("tracker_taxpayer_bucket",     "tracker_taxpayer_buc_org_id_44c42c81_fk_tracker_o",                  "org_id",          "tracker_organization"),
    ("tracker_timecardentry",       "tracker_timecardentr_org_id_996a4743_fk_tracker_o",                  "org_id",          "tracker_organization"),
    ("tracker_timesheet",           "tracker_timesheet_org_id_0402e194_fk_tracker_organization_id",       "org_id",          "tracker_organization"),
    ("tracker_userworkpattern",     "tracker_userworkpatt_org_id_6298f7d8_fk_tracker_o",                  "org_id",          "tracker_organization"),
]


def forwards(apps, schema_editor):
    for table, constraint, column, ref_table in CONSTRAINTS:
        schema_editor.execute(f"""
            ALTER TABLE {table}
            DROP CONSTRAINT "{constraint}";
            ALTER TABLE {table}
            ADD CONSTRAINT "{constraint}"
            FOREIGN KEY ({column}) REFERENCES {ref_table}(id)
            ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
        """)


def backwards(apps, schema_editor):
    for table, constraint, column, ref_table in CONSTRAINTS:
        schema_editor.execute(f"""
            ALTER TABLE {table}
            DROP CONSTRAINT "{constraint}";
            ALTER TABLE {table}
            ADD CONSTRAINT "{constraint}"
            FOREIGN KEY ({column}) REFERENCES {ref_table}(id)
            DEFERRABLE INITIALLY DEFERRED;
        """)


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0084_organization_deleted_at_organization_is_demo'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]