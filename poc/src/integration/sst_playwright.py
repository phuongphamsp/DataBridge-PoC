"""
SST Hanger Selector — Playwright Integration
Automates https://app.strongtie.com/hs to submit truss data and retrieve hanger results.
"""

import asyncio
import json
import time
from dataclasses import asdict, dataclass
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from src.models.sst_input import (
    SSTJoistInput, SSTTrussInput, SSTMultiTrussInput,
    SSTHipMember,
)

SST_URL = "https://app.strongtie.com/hs"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class HangerResult:
    model: str
    installed_cost: str
    width: str
    height: str
    bearing: str
    tf_depth: str
    tf_fasteners: str
    face_fasteners: str
    joist_fasteners: str
    download_lbs: str
    uplift_lbs: str


@dataclass
class SSTSubmitResult:
    filename: str
    connection_type: str
    success: bool
    error: Optional[str]
    hangers: list[HangerResult]
    raw_inputs_used: dict


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

async def _accept_eula(page: Page) -> None:
    """Dismiss the EULA modal if present."""
    try:
        await page.wait_for_selector(".fade.-eula.modal.show", timeout=5000)
        # Click the last button in modal footer (Accept)
        await page.click(".modal-footer button:last-child")
        await page.wait_for_selector(".fade.-eula.modal.show", state="hidden", timeout=5000)
    except Exception:
        pass  # EULA already accepted or not shown


async def _select_dropdown(page: Page, data_name: str, value: str) -> None:
    """
    Select a value in a Semantic UI custom dropdown identified by its name attribute.
    Passes data_name and value as JS arguments to avoid quoting/injection issues.
    """
    result = await page.evaluate(
        """([name, value]) => {
            let dd = document.querySelector('.ui.dropdown[name="' + name + '"]');
            if (!dd) return 'dropdown_not_found:' + name;
            if (dd.getBoundingClientRect().width === 0) return 'dropdown_hidden:' + name;
            dd.click();
            let items = dd.querySelectorAll('.item');
            let target = Array.from(items).find(i => i.textContent.trim() === value);
            if (!target) return 'item_not_found:' + Array.from(items).map(i => i.textContent.trim()).join('|');
            target.click();
            return 'ok';
        }""",
        [data_name, value]
    )
    if result != "ok":
        print(f"    [WARN] dropdown '{data_name}' = '{value}': {result}")


async def _fill_text(page: Page, name: str, value: str) -> None:
    """
    Fill a text input by its name attribute using React-compatible event dispatch.
    Uses the React internal fiber nativeInputValueSetter to trigger onChange.
    """
    result = await page.evaluate(
        """([name, value]) => {
            let inp = document.querySelector('input[name="' + name + '"]');
            if (!inp) return 'not_found:' + name;
            // Use React's internal setter to trigger synthetic onChange
            let nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(inp, value);
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            return 'ok';
        }""",
        [name, str(value)]
    )
    if result != "ok":
        print(f"    [WARN] text input '{name}' = '{value}': {result}")


async def _set_range_and_number(page: Page, name: str, value: float) -> None:
    """Set both the range slider and number input for angle fields using React-compatible events."""
    val_str = str(int(value)) if value == int(value) else str(value)
    await page.evaluate(
        """([name, val]) => {
            let nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            document.querySelectorAll('input[name="' + name + '"]').forEach(inp => {
                if (inp.type === 'number' || inp.type === 'range') {
                    nativeInputValueSetter.call(inp, val);
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                }
            });
        }""",
        [name, val_str]
    )


async def _click_connection_type(page: Page, conn_type: str) -> None:
    """Click the connection type button (Joist / Truss / Multi-Truss)."""
    labels = {
        "joist":      "Joist (Flush Top)",
        "truss":      "Truss (Flush Bottom)",
        "multiTruss": "Multi-Truss (Flush Bottom)",
    }
    label = labels.get(conn_type, "Joist (Flush Top)")
    await page.evaluate(f"""
        let btns = Array.from(document.querySelectorAll('button, [class*="button"]'));
        let btn = btns.find(b => b.textContent.trim() === '{label}' && b.getBoundingClientRect().width > 0);
        if (btn) btn.click();
    """)
    await page.wait_for_timeout(800)


async def _get_results(page: Page) -> list[HangerResult]:
    """
    Scrape the results table.
    Table structure (per row):
      td[0]: radio button (skip)
      td[1]: model name (via .hs__modelLink) + image
      td[2]: installed cost
      td[3]: width
      td[4]: height
      td[5]: bearing
      td[6]: tf_depth
      td[7]: tf_fasteners
      td[8]: face_fasteners
      td[9]: joist_fasteners
      td[10]: download_lbs
      td[11]: uplift_lbs
    """
    await page.wait_for_timeout(1500)
    rows = await page.evaluate("""
    () => {
        let results = [];
        document.querySelectorAll('tbody tr').forEach(row => {
            let cells = Array.from(row.querySelectorAll('td'));
            if (cells.length < 10) return;
            // Model name from .hs__modelLink button in cell[1]
            let modelLink = row.querySelector('.hs__modelLink');
            let model = modelLink ? modelLink.textContent.trim() : '';
            if (!model) return;  // skip rows without a model name (e.g. totals row)
            results.push({
                model:           model,
                installed_cost:  cells[2] ? cells[2].textContent.trim() : '',
                width:           cells[3] ? cells[3].textContent.trim() : '',
                height:          cells[4] ? cells[4].textContent.trim() : '',
                bearing:         cells[5] ? cells[5].textContent.trim() : '',
                tf_depth:        cells[6] ? cells[6].textContent.trim() : '',
                tf_fasteners:    cells[7] ? cells[7].textContent.trim() : '',
                face_fasteners:  cells[8] ? cells[8].textContent.trim() : '',
                joist_fasteners: cells[9] ? cells[9].textContent.trim() : '',
                download_lbs:    cells[10] ? cells[10].textContent.trim() : '',
                uplift_lbs:      cells[11] ? cells[11].textContent.trim() : '',
            });
        });
        return results;
    }
    """)
    return [HangerResult(**r) for r in rows]


# ---------------------------------------------------------------------------
# Form fillers per connection type
# ---------------------------------------------------------------------------

async def _fill_job_settings(page: Page, job, conn_type: str) -> None:
    await _select_dropdown(page, "jobSettings.hangerType",          job.hanger_type)
    await _select_dropdown(page, "jobSettings.fastenerType",        job.fastener_type)
    await _select_dropdown(page, "jobSettings.downloadDurationType", job.download_duration)
    await _select_dropdown(page, "jobSettings.upliftLoadDurationType", job.uplift_duration)
    await _fill_text(page, "jobSettings.jobID",    job.job_id)
    await _fill_text(page, "jobSettings.quantity", str(job.quantity))


async def _fill_hanger_options(page: Page, hanger) -> None:
    await _set_range_and_number(page, "hanger.skewAngle",              hanger.skew_angle)
    await _set_range_and_number(page, "hanger.slopeAngle",             hanger.slope_angle)
    await _set_range_and_number(page, "hanger.topFlangeOpenClosedAngle", hanger.top_flange_bend)
    await _set_range_and_number(page, "hanger.topFlangeSlopedDownAngle", hanger.top_flange_slope)
    await _select_dropdown(page, "topFlangeOffset", hanger.offset_direction)
    await _select_dropdown(page, "hlcFlush",        hanger.flush_position)


async def _fill_joist_form(page: Page, inp: SSTJoistInput) -> None:
    await _fill_job_settings(page, inp.job, "joist")
    # Header
    await _select_dropdown(page, "header.type",     inp.header_type)
    await _select_dropdown(page, "header.material", inp.header_species)
    await _select_dropdown(page, "header.width",    inp.header_width)
    await _select_dropdown(page, "header.depth",    inp.header_depth)
    await _select_dropdown(page, "header.ply",      str(inp.header_ply))
    await _fill_text(page, "header.memberID", inp.header_member_id)
    # Joist
    await _select_dropdown(page, "type",            inp.joist_type)
    await _select_dropdown(page, "joist.material",  inp.joist_species)
    await _select_dropdown(page, "joist.width",     inp.joist_width)
    await _select_dropdown(page, "joist.depth",     inp.joist_depth)
    await _select_dropdown(page, "ply",             str(inp.joist_ply))
    await _fill_text(page, "joist.memberID", inp.joist_member_id)
    await _fill_text(page, "joist.load",     str(int(inp.joist_load)))
    await _fill_text(page, "joist.uplift",   str(int(inp.joist_uplift)))
    # Hanger options
    await _fill_hanger_options(page, inp.hanger)


async def _fill_truss_form(page: Page, inp: SSTTrussInput) -> None:
    await _fill_job_settings(page, inp.job, "truss")
    await _select_dropdown(page, "jobSettings.ansitpi", inp.ansitpi)
    # Girder
    await _select_dropdown(page, "girder.type",     inp.girder_type)
    await _select_dropdown(page, "girder.material", inp.girder_species)
    await _select_dropdown(page, "girder.width",    inp.girder_width)
    await _select_dropdown(page, "girder.depth",    inp.girder_depth)
    await _select_dropdown(page, "girder.ply",      str(inp.girder_ply))
    await _fill_text(page, "girder.kingWidth",  str(inp.girder_king_width))
    await _fill_text(page, "girder.kingHeight", str(inp.girder_total_height))
    await _fill_text(page, "girder.memberID",   inp.girder_member_id)
    # Truss (carried)
    await _select_dropdown(page, "truss.type",     inp.truss_type)
    await _select_dropdown(page, "truss.material", inp.truss_species)
    await _select_dropdown(page, "truss.width",    inp.truss_width)
    await _fill_text(page, "truss.depth",    str(round(inp.truss_heel_height, 4)))
    await _select_dropdown(page, "truss.ply", str(inp.truss_ply))
    await _fill_text(page, "truss.memberID", inp.truss_member_id)
    await _fill_text(page, "truss.load",     str(int(inp.truss_load)))
    await _fill_text(page, "truss.uplift",   str(int(inp.truss_uplift)))
    # Hanger options
    await _fill_hanger_options(page, inp.hanger)


async def _fill_hip_member(page: Page, prefix: str, m: SSTHipMember) -> None:
    await _select_dropdown(page, f"{prefix}.type",     m.member_type)
    await _select_dropdown(page, f"{prefix}.material", m.species)
    await _select_dropdown(page, f"{prefix}.width",    m.width)
    await _select_dropdown(page, f"{prefix}.ply",      str(m.ply))
    await _fill_text(page, f"{prefix}.depth",    str(round(m.heel_height, 4)))
    await _fill_text(page, f"{prefix}.memberID", m.member_id)
    await _fill_text(page, f"{prefix}.load",     str(int(m.load)))
    await _fill_text(page, f"{prefix}.uplift",   str(int(m.uplift)))
    if prefix != "jack":
        await _set_range_and_number(page, f"{prefix}.skewAngle",  m.skew_angle)
    await _set_range_and_number(page, f"{prefix}.slopeAngle", m.slope_angle)


async def _fill_multitruss_form(page: Page, inp: SSTMultiTrussInput) -> None:
    await _fill_job_settings(page, inp.job, "multiTruss")
    await _select_dropdown(page, "configuration",       inp.configuration)
    await _select_dropdown(page, "jobSettings.ansitpi", inp.ansitpi)
    # Girder
    await _select_dropdown(page, "girder.type",     inp.girder_type)
    await _select_dropdown(page, "girder.material", inp.girder_species)
    await _select_dropdown(page, "girder.width",    inp.girder_width)
    await _select_dropdown(page, "girder.depth",    inp.girder_depth)
    await _select_dropdown(page, "girder.ply",      str(inp.girder_ply))
    await _fill_text(page, "girder.kingWidth",  str(inp.girder_king_width))
    await _fill_text(page, "girder.kingHeight", str(inp.girder_total_height))
    await _fill_text(page, "girder.memberID",   inp.girder_member_id)
    # Jack / Hip members
    await _fill_hip_member(page, "jack",     inp.jack)
    await _fill_hip_member(page, "leftHip",  inp.left_hip)
    await _fill_hip_member(page, "rightHip", inp.right_hip)


# ---------------------------------------------------------------------------
# Main submit function
# ---------------------------------------------------------------------------

async def submit_to_sst(
    sst_input,
    filename: str,
    headless: bool = True,
    timeout_ms: int = 30000,
) -> SSTSubmitResult:
    """
    Open SST Hanger Selector, fill the form with sst_input data, and return results.
    """
    conn_type = sst_input.connection_type
    raw = {}
    try:
        raw = asdict(sst_input)
    except Exception:
        pass

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(headless=headless)
        context: BrowserContext = await browser.new_context()
        page: Page = await context.new_page()

        try:
            await page.goto(SST_URL, wait_until="networkidle", timeout=timeout_ms)
            await page.wait_for_timeout(2000)

            # Accept EULA
            await _accept_eula(page)
            await page.wait_for_timeout(500)

            # Select connection type
            await _click_connection_type(page, conn_type)

            # Fill form
            if conn_type == "joist":
                await _fill_joist_form(page, sst_input)
            elif conn_type == "truss":
                await _fill_truss_form(page, sst_input)
            elif conn_type == "multiTruss":
                await _fill_multitruss_form(page, sst_input)

            await page.wait_for_timeout(1500)

            # Get results
            hangers = await _get_results(page)

            return SSTSubmitResult(
                filename=filename,
                connection_type=conn_type,
                success=True,
                error=None,
                hangers=hangers,
                raw_inputs_used=raw,
            )

        except Exception as e:
            return SSTSubmitResult(
                filename=filename,
                connection_type=conn_type,
                success=False,
                error=str(e),
                hangers=[],
                raw_inputs_used=raw,
            )
        finally:
            await browser.close()


def submit_sync(sst_input, filename: str, headless: bool = True) -> SSTSubmitResult:
    """Synchronous wrapper around submit_to_sst."""
    return asyncio.run(submit_to_sst(sst_input, filename, headless=headless))
