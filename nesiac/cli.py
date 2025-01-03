import time
import os
from typing import Optional
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.tree import Tree
from rich.table import Table
from rich.panel import Panel
from rich.console import Group, Console
from . import ingest
from .args import Args

if os.name == "nt":
    import msvcrt

    def get_key() -> Optional[int]:
        """Get a single key press for Windows."""
        if msvcrt.kbhit():
            return ord(msvcrt.getch())
        return None

else:
    import termios
    import sys
    import tty

    def get_key() -> Optional[int]:
        """Get a single key press for Unix-like systems."""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ord(ch) if ch else None


class InteractiveRegions:
    def __init__(self, reg: list[ingest.RegionWithSections]) -> None:
        self.regions = reg
        self.r_ix = 0
        self.s_ix = 0
        self.object_page = 0
        self.objects_per_page = 25
        self.sorted_by_size = True
        if len(self.selected_region().children) == 0:
            self._next_region_with_children()
        self.sort_by_size()

    def update_objs_per_page(self, con: Console):
        old = self.objects_per_page
        self.objects_per_page = max(con.height - 10, 1)
        if old != self.objects_per_page:
            self.object_page = 0

    def selected_region(self) -> ingest.RegionWithSections:
        return self.regions[self.r_ix]

    def selected_section(self) -> ingest.SectionWithObjects:
        return self.selected_region().children[self.s_ix]

    def set_selection_to(self, target: ingest.SectionWithObjects):
        for search_r, region in enumerate(self.regions):
            for search_s, section in enumerate(region.children):
                if section == target:
                    self.r_ix = search_r
                    self.s_ix = search_s

    def _next_region_with_children(self) -> bool:
        for ix in range(self.r_ix + 1, len(self.regions)):
            if len(self.regions[ix].children):
                self.r_ix = ix
                return True
        return False

    def _prev_region_with_children(self) -> bool:
        for ix in reversed(range(0, self.r_ix)):
            if len(self.regions[ix].children):
                self.r_ix = ix
                return True
        return False

    def next_section(self):
        # Advance to this region's next child if possible
        if (self.s_ix + 1) < len(self.selected_region().children):
            self.s_ix += 1
            self.object_page = 0
        else:
            # Otherwise move to the next region if possible
            if (self.r_ix + 1) < len(self.regions):
                if self._next_region_with_children():
                    self.s_ix = 0
                    self.object_page = 0

    def objects_in_view(self):
        return self.selected_section().children[
            self.object_page
            * self.objects_per_page : (self.object_page + 1)
            * self.objects_per_page
        ]

    def next_object_page(self):
        if ((self.object_page + 1) * self.objects_per_page) < len(
            self.selected_section().children
        ):
            self.object_page += 1

    def prev_object_page(self):
        if self.object_page > 0:
            self.object_page -= 1

    def prev_section(self):
        if self.s_ix > 0:
            self.s_ix -= 1
            self.object_page = 0
        else:
            if self.r_ix > 0:
                if self._prev_region_with_children():
                    self.s_ix = len(self.selected_region().children) - 1
                    self.object_page = 0

    def reg_section_text(self, reg: ingest.RegionWithSections) -> Text:
        fullness = reg.used_mem() / reg.data.length
        pc_colour = (
            "bright_red" if fullness > 0.9 else
            "bright_magenta" if fullness > 0.75 else
            ""
        )
        return Text.assemble(
            (reg.data.name, ""),
            " ",
            (f"{fullness:.0%}", pc_colour),
            style="on dark_blue" if reg == self.selected_region() else "",
            no_wrap=True,
        )

    def reg_totals_text(self, reg: ingest.RegionWithSections) -> Text:
        used_size = reg.used_mem()
        used_size_str = size_display(used_size)
        total_size_str = size_display(reg.data.length)
        return Text.assemble(
            (f"{used_size/reg.data.length:.0%}".ljust(4), "bright_green"),
            " | ",
            (f"{used_size_str}".rjust(6), "bright_yellow"),
            " of ",
            (f"{total_size_str}", "bright_yellow"),
        )

    def section_text(self, sec: ingest.SectionWithObjects, total_size: int) -> Text:
        return Text.assemble(
            (f"{sec.data.size/total_size:.0%}".ljust(4), "green"),
            " | ",
            (f"{size_display(sec.data.size)}".rjust(6), "yellow"),
            " | ",
            sec.data.name,
            style="on dark_blue" if sec == self.selected_section() else "",
            no_wrap=True,
        )

    def sort_by_size(self) -> None:
        original_selection = self.selected_section()
        self.sorted_by_size = True
        for region in self.regions:
            for section in region.children:
                section.children.sort(key=lambda x: x.size, reverse=True)
            region.children.sort(key=lambda x: x.data.size, reverse=True)
        self.set_selection_to(original_selection)
    
    def sort_by_name(self) -> None:
        original_selection = self.selected_section()
        self.sorted_by_size = False  # As we are sorting by name now, it's no longer size-based
        for region in self.regions:
            if len(region.children) == 0:
                continue
            for section in region.children:
                section.children.sort(key=lambda x: x.name.lower())  # Sorting by name
            region.children.sort(key=lambda s: s.data.name.lower())  # Sorting sections by name
        self.set_selection_to(original_selection)

    def sort_by_addr(self) -> None:
        original_selection = self.selected_section()
        self.sorted_by_size = False
        for region in self.regions:
            if len(region.children) == 0:
                continue
            for section in region.children:
                section.children.sort(key=lambda x: x.addr)
            region.children.sort(key=lambda s: s.data.addr)
        self.set_selection_to(original_selection)


def size_display(numbytes: int) -> str:
    megabyte = 1024 * 1024
    kilobyte = 1024
    if numbytes > megabyte:
        fval = numbytes / megabyte
        symbol = "M"
    elif numbytes > (kilobyte):
        fval = numbytes / kilobyte
        symbol = "K"
    else:
        return f"{numbytes} B"

    fmt_options = [
        f"{int(fval)}",
        f"{fval:.1f}",
        f"{fval:.2f}",
    ]

    chosen_format = max([f for f in fmt_options if len(f) <= 4], key=len)
    return chosen_format + " " + symbol

def whole_thing(o_data: InteractiveRegions, terminal_height: int) -> Layout:
    """Generate the entire display layout for the CLI application."""
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )

    # Header: Region Information
    header_text = Text(f"Selected Region: {o_data.selected_region().data.name}")
    header_text.stylize("bold green")
    header_panel = Panel(header_text, title="Region Overview", border_style="bright_blue")
    layout["header"].update(header_panel)

    # Body: Sections and Objects
    body_layout = Layout()
    body_layout.split_row(
        Layout(name="sections", ratio=1),
        Layout(name="objects", ratio=2),
    )

    # Sections
    sections_tree = Tree("Sections")
    for section in o_data.selected_region().children:
        section_text = o_data.section_text(section, o_data.selected_region().data.length)
        sections_tree.add(
            section_text,
            guide_style="bright_magenta",
            style="on bright_blue" if section == o_data.selected_section() else None,
        )

    body_layout["sections"].update(Panel(sections_tree, title="Sections"))

    # Objects in Selected Section
    objects_table = Table(title="Objects in Section")
    objects_table.add_column("Address", justify="right", style="cyan")
    objects_table.add_column("Size", justify="right", style="yellow")
    objects_table.add_column("Name", style="white")

    for obj in o_data.objects_in_view():
        objects_table.add_row(
            f"0x{obj.addr:X}",
            size_display(obj.size),
            obj.name,
        )

    body_layout["objects"].update(Panel(objects_table))

    layout["body"].update(body_layout)

    # Footer: Navigation Instructions
    footer_text = Text(
        "[W] Previous Section  [S] Next Section  [E] Previous Page  [D] Next Page  "
        "[Q] Toggle sort by Size/Address  [A] Sort by Name  [Esc] Exit"
    )
    footer_text.stylize("dim white")
    footer_panel = Panel(footer_text, title="Controls", border_style="bright_green")
    layout["footer"].update(footer_panel)

    return layout


def cli() -> None:
    """Main CLI entry point."""
    o_data = InteractiveRegions(ingest.ingest())
    console = Console()

    def render():
        live.update(whole_thing(o_data, console.height), refresh=True)

    with Live("", auto_refresh=False, console=console) as live:
        last_size = live.console.size
        o_data.update_objs_per_page(console)
        render()
        while True:
            if key := get_key():
                if key == ord("w"):
                    o_data.prev_section()
                    render()
                elif key == ord("s"):
                    o_data.next_section()
                    render()
                elif key == ord("e"):
                    o_data.prev_object_page()
                    render()
                elif key == ord("d"):
                    o_data.next_object_page()
                    render()
                elif key == ord("q"):
                    if o_data.sorted_by_size:
                        o_data.sort_by_addr()
                    else:
                        o_data.sort_by_size()
                    render()
                elif key == ord("a"):  # Add sorting by name on "A" key press
                    o_data.sort_by_name()
                    render()
                elif key == 27:  # Escape key
                    live.update("", refresh=True)
                    exit(0)
            else:
                if live.console.size != last_size:
                    last_size = live.console.size
                    o_data.update_objs_per_page(console)
                    render()
                time.sleep(0.05)


if __name__ == "__main__":
    cli()
