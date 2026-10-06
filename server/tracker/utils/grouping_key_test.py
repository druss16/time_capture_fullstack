"""Standalone tests for client_folder_bucket + the docs-family split it feeds.

Pure-function (no Django). Run:
    python server/tracker/utils/grouping_key_test.py
"""
import importlib.util
import os

# Load grouping_key.py directly by path — it's a pure module (only imports `re`),
# so we avoid tracker.utils.__init__ which pulls in Django.
_spec = importlib.util.spec_from_file_location(
    "grouping_key_pure",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "grouping_key.py"),
)
_gk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gk)
client_folder_bucket = _gk.client_folder_bucket
grouping_key = _gk.grouping_key


def _check(name, got, want):
    ok = got == want
    print(("PASS" if ok else "FAIL"), name, "->", repr(got), "" if ok else ("(want %r)" % (want,)))
    return ok


def run():
    results = []

    # --- client_folder_bucket: extracts the segment under a clients-root ---
    R = r"\\tlwall-dc-01\Company Data\Client File Notes"
    results.append(_check(
        "divine_mercy_folder",
        client_folder_bucket(R + r"\Divine Mercy\2025-2026\Financials\June 2026\Preliminary\Divine Mercy Transfers JUN26.xlsx"),
        "divine mercy"))
    results.append(_check(
        "oloh_deep_subfolder",
        client_folder_bucket(R + r"\Our Lady of Hope\2025-2026\Financial Statements\MAY26\OLOH P&L Detail FYTD MAY26.xlsx"),
        "our lady of hope"))
    results.append(_check(
        "oloh_at_client_root",
        client_folder_bucket(R + r"\Our Lady of Hope\Our Lady of Hope Client Information.xlsx"),
        "our lady of hope"))

    # SAME client, two DIFFERENT sub-folders -> SAME bucket (no within-client split)
    a = client_folder_bucket(R + r"\Divine Mercy\A\x.xlsx")
    bb = client_folder_bucket(R + r"\Divine Mercy\B\C\y.xlsx")
    results.append(_check("same_client_same_bucket", a == bb and a == "divine mercy", True))

    # --- no recognized clients-root -> '' (unaffected: keeps coarse "docs") ---
    results.append(_check(
        "user_onedrive_no_bucket",
        client_folder_bucket(r"C:\Users\wayne.AD\OneDrive - TL Wall Accounting and Tax Corp\Documents\Victoria porter.xlsx"),
        ""))
    results.append(_check("empty_path", client_folder_bucket(""), ""))
    results.append(_check("no_path_none", client_folder_bucket(None), ""))

    # forward-slash / mixed separators
    results.append(_check(
        "forward_slashes",
        client_folder_bucket("//srv/Clients/Grace Episcopal Church/2026/x.xlsx"),
        "grace episcopal church"))

    # a 1-2 char folder after the root is not a real client folder
    results.append(_check(
        "too_short_folder",
        client_folder_bucket(R + r"\AB\file.xlsx"),
        ""))

    # --- Dropbox root: one top-level folder per client (marketing agency) ---
    for name, path, want in (
        ("dropbox_cloudstorage",
         "/Users/amy/Library/CloudStorage/Dropbox/D&F CPAs/Social/FB Cover.psd", "d&f cpas"),
        ("dropbox_cloudstorage_team",
         "/Users/amy/Library/CloudStorage/Dropbox-Bright Agency/Aurelia Salon/Web/hero.psd",
         "aurelia salon"),
        ("dropbox_legacy_home", "/Users/amy/Dropbox/Aurelia Salon/logo.ai", "aurelia salon"),
        ("dropbox_legacy_team",
         "/Users/amy/Dropbox (Bright Agency)/GrowU/EIN/GrowU_EIN_Doc.pdf", "growu"),
        ("dropbox_windows", r"C:\Users\amy\Dropbox\Aurelia Salon\Proposal.pdf", "aurelia salon"),
        ("dropbox_windows_team", r"C:\Users\amy\Dropbox (Bright Agency)\GrowU\a.docx", "growu"),
        # A deeper NAMED clients-root still wins over the Dropbox root.
        ("dropbox_inner_clients_root_wins",
         "/Users/amy/Library/CloudStorage/Dropbox/Firm/Clients/Acme/2026/x.xlsx", "acme"),
        ("dropbox_inner_client_file_notes_wins",
         r"C:\Users\wayne\Dropbox\TL Wall\Client File Notes\Divine Mercy\x.xlsx", "divine mercy"),
        # A file saved straight into Dropbox names no client folder.
        ("dropbox_file_at_root", "/Users/amy/Library/CloudStorage/Dropbox/notes.pdf", ""),
        ("dropbox_bare_root", "/Users/amy/Dropbox", ""),
        # Only real Dropbox root shapes — not any segment containing "dropbox".
        ("dropbox_word_in_folder", "/Users/amy/Work/Old Dropbox Export/Acme/x.pdf", ""),
        ("dropbox_nested_not_root", "/Users/amy/Work/Dropbox/Acme/x.pdf", ""),
        ("dropbox_dash_outside_cloudstorage", "/Users/amy/Dropbox-backup/Acme/x.pdf", ""),
        ("dropbox_cloudstorage_other_provider",
         "/Users/amy/Library/CloudStorage/OneDrive-Personal/Acme/x.pdf", ""),
    ):
        results.append(_check(name, client_folder_bucket(path), want))

    # --- Home Desktop / Documents: the last-resort anchor ---
    # The real case: ~10s on a D&F file, then Nike work, merged into one
    # Photoshop block booked to Dauphin & Fantacone.
    nike = "/Users/danrussell/Desktop/Nike/Spring Launch/Nike_test.psd"
    dnf = "/Users/danrussell/Desktop/Dauphin & Fantacone/D&F_trois.psd"
    results.append(_check("desktop_nike", client_folder_bucket(nike), "nike"))
    results.append(_check("desktop_dnf", client_folder_bucket(dnf), "dauphin & fantacone"))
    results.append(_check("desktop_two_clients_split",
                          client_folder_bucket(nike) != client_folder_bucket(dnf), True))
    results.append(_check(
        "desktop_same_client_two_projects_same_bucket",
        client_folder_bucket("/Users/dan/Desktop/Nike/Fall Promo/a.psd")
        == client_folder_bucket(nike.replace("danrussell", "dan")), True))
    for name, path, want in (
        ("documents_mac", "/Users/amy/Documents/Aurelia Salon/logo.ai", "aurelia salon"),
        ("desktop_windows", r"C:\Users\amy\Desktop\GrowU\EIN\a.pdf", "growu"),
        ("documents_linux", "/home/amy/Documents/Acme/x.docx", "acme"),
        ("onedrive_desktop_windows",
         r"C:\Users\wayne\OneDrive - TL Wall Accounting\Desktop\Divine Mercy\x.xlsx", "divine mercy"),
        ("onedrive_plain_documents", r"C:\Users\wayne\OneDrive\Documents\Acme\x.xlsx", "acme"),
        ("onedrive_cloudstorage_mac",
         "/Users/amy/Library/CloudStorage/OneDrive-Bright/Documents/Acme/x.pdf", "acme"),
        # A file saved straight onto the Desktop names no client folder.
        ("desktop_file_at_root", "/Users/amy/Desktop/notes.psd", ""),
        ("desktop_bare", "/Users/amy/Desktop", ""),
        # Only the HOME-level folder, not any segment named Desktop/Documents.
        ("documents_nested_not_home", "/Volumes/Share/Documents/Acme/x.pdf", ""),
        ("documents_deep_not_home", "/Users/amy/Projects/Documents/Acme/x.pdf", ""),
        ("downloads_not_an_anchor", "/Users/amy/Downloads/Acme/x.pdf", ""),
        # Named clients-root and Dropbox root still win over the Desktop.
        ("desktop_inner_clients_root_wins",
         "/Users/amy/Desktop/Work/Clients/Acme/x.pdf", "acme"),
        ("dropbox_wins_over_documents",
         "/Users/amy/Dropbox/Aurelia Salon/Documents/x.pdf", "aurelia salon"),
    ):
        results.append(_check(name, client_folder_bucket(path), want))

    # org 21's real shape is unchanged.
    results.append(_check(
        "org21_unchanged_by_dropbox_rule",
        client_folder_bucket(R + r"\Divine Mercy\2025-2026\x.xlsx"),
        "divine mercy"))

    # --- grouping_key still collapses generic docs to the coarse bucket
    #     (the folder refinement lives in compaction._grouping_content_id) ---
    results.append(_check("grouping_key_generic_doc", grouping_key("file=some account spreadsheet.xlsx"), "docs"))
    results.append(_check("grouping_key_qbo_customer", grouping_key("qbo:customer=acme inc"), "qbo:customer=acme inc"))

    print()
    n_pass = sum(1 for r in results if r)
    print("%d/%d passed" % (n_pass, len(results)))
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(run())
