#!/usr/bin/env python3

import sys
import os
import random
import subprocess
import signal
import select
import termios
import tty
import shutil
from collections import deque

# ==========================================
# CONFIGURATION & INITIALIZATION
# ==========================================
def parse_arguments():
    args = sys.argv[1:]
    
    ops_path = None
    nums_path = None
    
    # Extract --ops and --nums flags
    i = 0
    while i < len(args):
        if args[i] == '--ops':
            if i + 1 >= len(args):
                print("Error: --ops requires a path argument.")
                sys.exit(1)
            ops_path = args[i + 1]
            if not os.path.isfile(ops_path):
                print(f"Error: ops file '{ops_path}' not found.")
                sys.exit(1)
            args = args[:i] + args[i+2:]
        elif args[i] == '--nums':
            if i + 1 >= len(args):
                print("Error: --nums requires a path argument.")
                sys.exit(1)
            nums_path = args[i + 1]
            if not os.path.isfile(nums_path):
                print(f"Error: nums file '{nums_path}' not found.")
                sys.exit(1)
            args = args[:i] + args[i+2:]
        else:
            i += 1
    
    # If --ops is passed, --nums is required and push_swap path is optional
    if ops_path is not None and nums_path is None:
        print("Error: --ops requires --nums to be passed as well.")
        sys.exit(1)
    
    target_executable = None
    n_elems = 500
    max_disorder = 50
    
    if ops_path is not None:
        # --ops passed: push_swap path is optional, no n_elems/max_disorder
        if len(args) > 1:
            print(f"Usage: {sys.argv[0]} [--ops <ops_file>] [--nums <nums_file>] [<path_to_push_swap>]")
            sys.exit(1)
        if len(args) == 1:
            target_executable = args[0]
            if not os.path.isfile(target_executable) or not os.access(target_executable, os.X_OK):
                print(f"Error: '{target_executable}' is not a valid or executable file.")
                sys.exit(1)
    else:
        # Normal mode or --nums only: push_swap path is required
        if len(args) < 1 or len(args) > 3:
            print(f"Usage: {sys.argv[0]} [--nums <nums_file>] <path_to_push_swap> [number_of_elements] [max_disorder_percentage]")
            sys.exit(1)
        target_executable = args[0]
        if not os.path.isfile(target_executable) or not os.access(target_executable, os.X_OK):
            print(f"Error: '{target_executable}' is not a valid or executable file.")
            sys.exit(1)
        
        if len(args) >= 2:
            try:
                n_elems = int(args[1])
                if n_elems <= 0:
                    raise ValueError
            except ValueError:
                print("Error: number_of_elements must be a positive integer.")
                sys.exit(1)
                
        if len(args) == 3:
            try:
                max_disorder = int(args[2])
                if max_disorder < 0 or max_disorder > 55:
                    raise ValueError
            except ValueError:
                print("Error: max_disorder_percentage must be between 0 and 55.")
                sys.exit(1)
    
    return target_executable, n_elems, max_disorder, ops_path, nums_path

# ==========================================
# TERMINAL CONTEXT MANAGER
# ==========================================
class TerminalTUI:
    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.old_settings = None

    def __enter__(self):
        self.old_settings = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\033[?1049h\033[?25l")
        sys.stdout.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.write("\033[0m\033[?25h\033[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)

def get_key(timeout):
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if r:
        data = os.read(sys.stdin.fileno(), 3)
        if len(data) >= 1:
            return data.decode('utf-8', 'ignore')
    return None

# ==========================================
# VISUALIZER ENGINE
# ==========================================
class PushSwapVisualizer:
    def __init__(self, target_executable, n_elems, max_disorder, ops_path=None, nums_path=None):
        self.target_executable = target_executable
        self.n_elems = n_elems
        self.disorder = max_disorder
        self.ops_path = ops_path
        self.nums_path = nums_path
        self.has_ops = ops_path is not None
        self.has_nums = nums_path is not None
        self.actual_disorder = 0.0
        
        self.make_dir = None
        self.binary_name = "push_swap"
        if target_executable is not None:
            self.make_dir = os.path.dirname(os.path.abspath(target_executable))
            self.binary_name = os.path.basename(target_executable)
        
        self.allowed_sizes = [10, 50, 100, 200, 500, 1000]
        if self.n_elems not in self.allowed_sizes:
            self.allowed_sizes.append(self.n_elems)
            self.allowed_sizes.sort()
            
        self.stack_a = deque()
        self.stack_b = deque()
        self.ops = []
        self.total_ops = 0
        self.op_idx = 0
        
        # New mode/flags integration
        self.flags = ["--adaptive", "--simple", "--medium", "--complex"]
        self.flag_idx = 0

        self.force_redraw = True
        self.auto_play = False
        self.play_dir = "FWD"
        self.ordered_status = None  # None = ?, "OK" = green, "KO" = red
        
        self.fps = 30
        self.frame_delay = 1.0 / self.fps
        self.speeds = [1, 5, 10, 30, 60, 150, 300, 600, 1200, 3000, 6000, 12000, 50000, 100000]
        self.speed_idx = 5
        self.accumulator = 0

    def compute_disorder(self, sequence):
        n = len(sequence)
        if n < 2:
            return 0.0
            
        def count_inversions(arr):
            if len(arr) <= 1:
                return arr, 0
            mid = len(arr) // 2
            left, inv_left = count_inversions(arr[:mid])
            right, inv_right = count_inversions(arr[mid:])
            merged, inv_merge = merge(left, right)
            return merged, inv_left + inv_right + inv_merge

        def merge(left, right):
            merged = []
            inv_count = 0
            i, j = 0, 0
            while i < len(left) and j < len(right):
                if left[i] <= right[j]:
                    merged.append(left[i])
                    i += 1
                else:
                    merged.append(right[j])
                    inv_count += len(left) - i
                    j += 1
            merged += left[i:]
            merged += right[j:]
            return merged, inv_count

        _, mistakes = count_inversions(list(sequence))
        total_pairs = (n * (n - 1)) / 2.0
        
        return (mistakes / total_pairs) * 100.0

    def generate_data(self):
        self.auto_play = False
        self.op_idx = 0
        self.accumulator = 0
        self.ops = []
        self.total_ops = 0
        self.ordered_status = None
        
        sys.stdout.write("\033[2J\033[H\033[1;36mGenerating data and running push_swap... Please wait.\033[0m\r\n")
        sys.stdout.flush()

        # Load or generate numbers
        if self.nums_path:
            with open(self.nums_path, 'r') as f:
                content = f.read().strip()
            raw_sequence = [int(x) for x in content.split()]
            self.n_elems = len(raw_sequence)
            # Update allowed_sizes if needed
            if self.n_elems not in self.allowed_sizes:
                self.allowed_sizes.append(self.n_elems)
                self.allowed_sizes.sort()
        else:
            raw_sequence = random.sample(range(-1000000, 1000000), self.n_elems)
            raw_sequence.sort()

            n = self.n_elems
            total_pairs = (n * (n - 1)) / 2.0
            target_inv = int((self.disorder / 100.0) * total_pairs)

            if target_inv > 0:
                inv = [0] * n
                indices = list(range(n))
                random.shuffle(indices)
                
                remaining = target_inv
                for i in indices:
                    max_cap = n - 1 - i
                    take = random.randint(0, min(remaining, max_cap))
                    inv[i] = take
                    remaining -= take
                    
                if remaining > 0:
                    random.shuffle(indices)
                    for i in indices:
                        max_cap = n - 1 - i
                        space = max_cap - inv[i]
                        if space > 0:
                            take = min(remaining, space)
                            inv[i] += take
                            remaining -= take
                        if remaining == 0:
                            break

                result_sequence = []
                for i in range(n - 1, -1, -1):
                    val = raw_sequence[i]
                    insert_pos = inv[i]
                    result_sequence.insert(insert_pos, val)
                    
                raw_sequence = result_sequence

        self.actual_disorder = self.compute_disorder(raw_sequence)

        # Load ops from file or run push_swap
        if self.ops_path:
            with open(self.ops_path, 'r') as f:
                content = f.read().strip()
            self.ops = content.split() if content else []
            self.total_ops = len(self.ops)
        else:
            str_seq = [str(x) for x in raw_sequence]
            current_flag = self.flags[self.flag_idx]
            
            result = subprocess.run(
                [self.target_executable, current_flag] + str_seq,
                capture_output=True,
                text=True,
                check=False
            )
            self.ops = result.stdout.strip().split()
            self.total_ops = len(self.ops)
        
            
        sorted_seq = sorted(raw_sequence)
        rank_map = {val: i + 1 for i, val in enumerate(sorted_seq)}
        ranks_sequence = [rank_map[val] for val in raw_sequence]
        
        self.stack_a = deque(ranks_sequence)
        self.stack_b = deque()
        self.force_redraw = True

    def handle_resize(self, signum, frame):
        self.force_redraw = True

    def exec_op(self, op):
        if op == "sa" and len(self.stack_a) >= 2:
            self.stack_a[0], self.stack_a[1] = self.stack_a[1], self.stack_a[0]
        elif op == "sb" and len(self.stack_b) >= 2:
            self.stack_b[0], self.stack_b[1] = self.stack_b[1], self.stack_b[0]
        elif op == "ss":
            self.exec_op("sa"); self.exec_op("sb")
        elif op == "pa" and len(self.stack_b) >= 1:
            self.stack_a.appendleft(self.stack_b.popleft())
        elif op == "pb" and len(self.stack_a) >= 1:
            self.stack_b.appendleft(self.stack_a.popleft())
        elif op == "ra" and len(self.stack_a) >= 2:
            self.stack_a.append(self.stack_a.popleft())
        elif op == "rb" and len(self.stack_b) >= 2:
            self.stack_b.append(self.stack_b.popleft())
        elif op == "rr":
            self.exec_op("ra"); self.exec_op("rb")
        elif op == "rra" and len(self.stack_a) >= 2:
            self.stack_a.appendleft(self.stack_a.pop())
        elif op == "rrb" and len(self.stack_b) >= 2:
            self.stack_b.appendleft(self.stack_b.pop())
        elif op == "rrr":
            self.exec_op("rra"); self.exec_op("rrb")

    def exec_inv_op(self, op):
        inv_map = {
            "sa": "sa", "sb": "sb", "ss": "ss",
            "pa": "pb", "pb": "pa",
            "ra": "rra", "rb": "rrb", "rr": "rrr",
            "rra": "ra", "rrb": "rb", "rrr": "rr"
        }
        if op in inv_map:
            self.exec_op(inv_map[op])

    def check_ordered(self):
        if len(self.stack_b) != 0:
            self.ordered_status = "KO"
            return
        lst = list(self.stack_a)
        if all(lst[i] <= lst[i+1] for i in range(len(lst)-1)):
            self.ordered_status = "OK"
        else:
            self.ordered_status = "KO"

    def get_rgb(self, val, max_val):
        if val <= 0: return "0;0;0"
        ratio = val / max_val
        if ratio < 0.25:
            return f"0;{int((ratio/0.25)*255)};255"
        elif ratio < 0.5:
            return f"0;255;{int((1-(ratio-0.25)/0.25)*255)}"
        elif ratio < 0.75:
            return f"{int(((ratio-0.5)/0.25)*255)};255;0"
        else:
            return f"255;{int((1-(ratio-0.75)/0.25)*255)};0"

    def build_bar(self, val1, val2, max_w):
        if val1 == -1 and val2 == -1:
            return " " * max_w

        l1 = int((val1 * max_w) / self.n_elems) if val1 > 0 else 0
        l2 = int((val2 * max_w) / self.n_elems) if val2 > 0 else 0
        
        if val1 > 0 and l1 == 0: l1 = 1
        if val2 > 0 and l2 == 0: l2 = 1

        rgb1 = self.get_rgb(val1, self.n_elems)
        rgb2 = self.get_rgb(val2, self.n_elems)

        min_l = min(l1, l2)
        max_l = max(l1, l2)
        
        out = ""
        if min_l > 0:
            out += f"\033[38;2;{rgb1}m\033[48;2;{rgb2}m" + ("▀" * min_l) + "\033[0m"
            
        if l1 > l2:
            out += f"\033[38;2;{rgb1}m\033[49m" + ("▀" * (l1 - min_l)) + "\033[0m"
        elif l2 > l1:
            out += f"\033[38;2;{rgb2}m\033[49m" + ("▄" * (l2 - min_l)) + "\033[0m"
            
        spaces = max_w - max_l
        if spaces > 0:
            out += " " * spaces
            
        return out

    def layout_items(self, items, default_chunk, cols):
        chunks = [items[i:i + default_chunk] for i in range(0, len(items), default_chunk)]
        fits = all(sum(it[0] for it in chunk) + (len(chunk) - 1) * 3 + 2 <= cols - 2 for chunk in chunks)
        
        if fits:
            return chunks
            
        for chunk_size in range(4, 0, -1):
            chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
            fits = all(sum(it[0] for it in chunk) + (len(chunk) - 1) * 3 + 2 <= cols - 2 for chunk in chunks)
            if fits:
                return chunks
                
        return [[item] for item in items]

    def sample_stack(self, stack, m_slots):
        length = len(stack)
        if length == 0: return []
        if length <= m_slots: return list(stack)
        return [stack[int(k * (length - 1) / (m_slots - 1))] if m_slots > 1 else stack[0] for k in range(m_slots)]

    def draw_screen(self):
        cols, lines = shutil.get_terminal_size()
        
        clear_cmd = "\033[H"
        if self.force_redraw:
            clear_cmd = "\033[2J\033[H"
            self.force_redraw = False
            
        c_rst = "\033[0m"; c_dim = "\033[2m"; c_bold = "\033[1m"
        c_cyan = "\033[1;36m"; c_yellow = "\033[1;33m"; c_green = "\033[1;32m"
        c_red = "\033[1;31m"; c_magenta = "\033[1;35m"; c_frame = "\033[38;5;60m"
        
        speed_val = self.speeds[self.speed_idx]
        auto_str = "ON" if self.auto_play else "OFF"
        auto_col = c_green if self.auto_play else c_red
        dir_col = c_cyan if self.play_dir == "FWD" else c_magenta
        mode_str = self.flags[self.flag_idx]
        
        if self.ordered_status is None:
            ordered_str = f"Ordered: {c_dim}?{c_rst}"
            ordered_plain = len("Ordered: ?")
        elif self.ordered_status == "OK":
            ordered_str = f"Ordered: {c_green}OK{c_rst}"
            ordered_plain = len("Ordered: OK")
        else:
            ordered_str = f"Ordered: {c_red}KO{c_rst}"
            ordered_plain = len("Ordered: KO")
        
        top_items = [
            (len("push_swap visualizer"), f"{c_cyan}push_swap visualizer{c_rst}"),
            (len(f"Nums: {self.n_elems}"), f"{c_yellow}Nums: {self.n_elems}{c_rst}"),
            (len(f"Mode: {mode_str}"), f"{c_green}Mode: {mode_str}{c_rst}"),
            (len(f"Disorder: {self.actual_disorder:.1f}%"), f"{c_magenta}Disorder: {self.actual_disorder:.1f}%{c_rst}"),
            (len(f"Ops: {self.op_idx}/{self.total_ops}"), f"{c_bold}Ops: {self.op_idx}/{self.total_ops}{c_rst}"),
            (len(f"Auto: {auto_str} ({self.play_dir})"), f"Auto: {auto_col}{auto_str}{c_rst} ({dir_col}{self.play_dir}{c_rst})"),
            (len(f"Speed: {speed_val}/s"), f"{c_bold}Speed: {speed_val}/s{c_rst}"),
            (ordered_plain, ordered_str)
        ]
        
        bottom_items = [
            (len("[P] Play/Pause"), f"[{c_dim}P{c_rst}] Play/Pause"),
            (len("[O] Fwd/Rev"), f"[{c_dim}O{c_rst}] Fwd/Rev"),
            (len("[N] Next"), f"[{c_dim}N{c_rst}] Next"),
            (len("[B] Back"), f"[{c_dim}B{c_rst}] Back"),
            (len("[Z] Speed-"), f"[{c_dim}Z{c_rst}] Speed-"),
            (len("[X] Speed+"), f"[{c_dim}X{c_rst}] Speed+"),
            (len("[E] Check"), f"[{c_yellow}E{c_rst}] Check"),
        ]
        
        if not self.has_ops:
            if not self.has_nums:
                bottom_items.append((len("[G] Re-gen"), f"[{c_yellow}G{c_rst}] Re-gen"))
            bottom_items.append((len("[M] Mode"), f"[{c_green}M{c_rst}] Mode"))
        
        if not self.has_ops and not self.has_nums:
            bottom_items.append((len("[A] Nums-"), f"[{c_cyan}A{c_rst}] Nums-"))
            bottom_items.append((len("[S] Nums+"), f"[{c_cyan}S{c_rst}] Nums+"))
            bottom_items.append((len("[D] Disorder-"), f"[{c_magenta}D{c_rst}] Disorder-"))
            bottom_items.append((len("[F] Disorder+"), f"[{c_magenta}F{c_rst}] Disorder+"))
        
        if not self.has_ops and self.target_executable is not None:
            bottom_items.append((len("[C] Make"), f"[{c_yellow}C{c_rst}] Make"))
        
        bottom_items.append((len("[Q] Quit"), f"[{c_red}Q{c_rst}] Quit"))
        
        top_chunks = self.layout_items(top_items, 3, cols)
        bottom_chunks = self.layout_items(bottom_items, 6, cols)
        
        occupied_lines = len(top_chunks) + len(bottom_chunks) + 5
        max_lines = max(lines - occupied_lines, 1)
        max_slots = max_lines * 2
        
        out = [clear_cmd, "\033[0m"]
        
        # --- DRAW TOP BOX ---
        out.append(f"{c_frame}╭{'─' * (cols-2)}╮{c_rst}\033[K\r\n")
        for chunk in top_chunks:
            plain_len = sum(item[0] for item in chunk) + (len(chunk) - 1) * 3
            pad = cols - 2 - plain_len
            pad_l = max(pad // 2, 0)
            pad_r = max(pad - pad_l, 0)
            colored_str = f" {c_dim}|{c_rst} ".join(item[1] for item in chunk)
            out.append(f"{c_frame}│{c_rst}{' ' * pad_l}{colored_str}{' ' * pad_r}{c_frame}│{c_rst}\033[K\r\n")
        out.append(f"{c_frame}╰{'─' * (cols-2)}╯{c_rst}\033[K\r\n")
        
        # --- DRAW STACKS ---
        half_cols = max((cols - 5) // 2, 0)
        hdr_a = f"{c_rst}STACK A{c_rst}"
        hdr_b = f"{c_rst}STACK B{c_rst}"
        pad_a_len = max(half_cols - 7, 0)
        out.append(f" {hdr_a}{' ' * pad_a_len} {c_dim}│{c_rst} {hdr_b}\033[K\r\n")
        
        disp_sa = self.sample_stack(self.stack_a, max_slots)
        disp_sb = self.sample_stack(self.stack_b, max_slots)
        
        disp_sa_len = len(disp_sa)
        disp_sb_len = len(disp_sb)
        
        for i in range(max_lines):
            idx1, idx2 = i * 2, i * 2 + 1
            
            a1 = disp_sa[idx1] if idx1 < disp_sa_len else -1
            a2 = disp_sa[idx2] if idx2 < disp_sa_len else -1
            b1 = disp_sb[idx1] if idx1 < disp_sb_len else -1
            b2 = disp_sb[idx2] if idx2 < disp_sb_len else -1
            
            str_a = self.build_bar(a1, a2, half_cols)
            str_b = self.build_bar(b1, b2, half_cols)
            
            out.append(f" {str_a} \033[0m{c_dim}│\033[0m {str_b} \033[0m\033[K\r\n")
            
        # --- DRAW BOTTOM BOX ---
        out.append(f"{c_frame}╭{'─' * (cols-2)}╮{c_rst}\033[K\r\n")
        for chunk in bottom_chunks:
            plain_len = sum(item[0] for item in chunk) + (len(chunk) - 1) * 3
            pad = cols - 2 - plain_len
            pad_l = max(pad // 2, 0)
            pad_r = max(pad - pad_l, 0)
            colored_str = f" {c_dim}|{c_rst} ".join(item[1] for item in chunk)
            out.append(f"{c_frame}│{c_rst}{' ' * pad_l}{colored_str}{' ' * pad_r}{c_frame}│{c_rst}\033[K\r\n")
        out.append(f"{c_frame}╰{'─' * (cols-2)}╯{c_rst}\033[K")
        
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def change_elems(self, direction):
        try:
            curr_idx = self.allowed_sizes.index(self.n_elems)
        except ValueError:
            self.allowed_sizes.append(self.n_elems)
            self.allowed_sizes.sort()
            curr_idx = self.allowed_sizes.index(self.n_elems)
            
        new_idx = curr_idx + direction
        if 0 <= new_idx < len(self.allowed_sizes):
            self.n_elems = self.allowed_sizes[new_idx]
            self.generate_data()

    def change_disorder(self, direction):
        new_val = self.disorder + (direction * 5)
        if 0 <= new_val <= 55:
            self.disorder = new_val
            self.generate_data()

    def show_make_screen(self, make_re=False):
        c_rst = "\033[0m"; c_bold = "\033[1m"; c_cyan = "\033[1;36m"
        c_green = "\033[1;32m"; c_red = "\033[1;31m"; c_yellow = "\033[1;33m"
        c_dim = "\033[2m"
        
        cmd = "make re" if make_re else "make"
        
        # Run the command and collect output
        output_lines = [f"{c_cyan}Running '{cmd}' in {self.make_dir}...{c_rst}", ""]
        
        try:
            result = subprocess.run(
                cmd,
                cwd=self.make_dir,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.stdout:
                output_lines.extend(result.stdout.split('\n'))
            if result.stderr:
                output_lines.extend([f"{c_red}{line}{c_rst}" for line in result.stderr.split('\n')])
            
            output_lines.append(f"\n{c_bold}Exit code: {result.returncode}{c_rst}")
        except Exception as e:
            output_lines.append(f"{c_red}Error running {cmd}: {e}{c_rst}")
        
        # Scroll state
        scroll_offset = 0
        
        while True:
            cols, lines = shutil.get_terminal_size()
            
            # Footer always takes 3-4 lines
            binary_path = os.path.join(self.make_dir, self.binary_name)
            binary_exists = os.path.isfile(binary_path)
            
            footer_lines = 3
            if not binary_exists:
                footer_lines = 4
            
            max_content_lines = max(lines - footer_lines, 1)
            total_lines = len(output_lines)
            
            # Clamp scroll offset
            max_scroll = max(total_lines - max_content_lines, 0)
            scroll_offset = min(scroll_offset, max_scroll)
            
            # Draw
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            
            visible = output_lines[scroll_offset:scroll_offset + max_content_lines]
            for line in visible:
                # Truncate long lines to avoid wrapping issues
                if len(line) > cols - 1:
                    line = line[:cols - 1]
                print(line)
            
            # Fill remaining space
            for _ in range(max_content_lines - len(visible)):
                print()
            
            # Footer
            print(f"\n{'='*min(60, cols)}")
            print(f"{c_green}[W] Back{c_rst} | {c_yellow}[C] Make{c_rst} | {c_yellow}[R] Make re{c_rst} | {c_red}[Q] Quit{c_rst} | {c_dim}↑/↓ Scroll{c_rst}")
            if not binary_exists:
                print(f"{c_red}Warning: Binary '{self.binary_name}' not found!{c_rst}")
            
            sys.stdout.flush()
            
            while True:
                key = get_key(None)
                if key:
                    if key == '\x1b[A' or key.lower() == 'k':  # Up arrow or K
                        scroll_offset = max(scroll_offset - 1, 0)
                        break
                    elif key == '\x1b[B' or key.lower() == 'j':  # Down arrow or J
                        scroll_offset = min(scroll_offset + 1, max_scroll)
                        break
                    elif key.startswith("\x1b"):
                        continue
                    k = key.lower()
                    if k == 'w':
                        # Check binary existence at the moment W is pressed
                        binary_path = os.path.join(self.make_dir, self.binary_name)
                        if os.path.isfile(binary_path):
                            self.force_redraw = True
                            return
                        else:
                            sys.stdout.write(f"\n{c_red}Binary '{self.binary_name}' not found. Cannot return to visualizer.{c_rst}\n")
                            sys.stdout.flush()
                    elif k == 'c':
                        self.show_make_screen(make_re=False)
                        return
                    elif k == 'r':
                        self.show_make_screen(make_re=True)
                        return
                    elif k == 'q':
                        sys.exit(0)

    def run(self):
        self.generate_data()
        
        signal.signal(signal.SIGWINCH, self.handle_resize)
        
        def quit_signal(sig, frame):
            sys.exit(0)
            
        signal.signal(signal.SIGINT, quit_signal)
        signal.signal(signal.SIGTERM, quit_signal)

        with TerminalTUI():
            while True:
                if self.auto_play:
                    target_ops_sec = self.speeds[self.speed_idx]
                    self.accumulator += target_ops_sec
                    ops_this_frame = self.accumulator // self.fps
                    self.accumulator %= self.fps

                    for _ in range(ops_this_frame):
                        if self.play_dir == "FWD":
                            if self.op_idx < self.total_ops:
                                self.exec_op(self.ops[self.op_idx])
                                self.op_idx += 1
                            else:
                                self.auto_play = False
                                self.accumulator = 0
                                break
                        else:
                            if self.op_idx > 0:
                                self.op_idx -= 1
                                self.exec_inv_op(self.ops[self.op_idx])
                            else:
                                self.auto_play = False
                                self.accumulator = 0
                                break

                self.draw_screen()
                
                key = get_key(self.frame_delay)
                if key:
                    if key.startswith("\x1b"): 
                        continue
                    
                    k = key.lower()
                    if k == 'p':
                        self.auto_play = not self.auto_play
                        if not self.auto_play: self.accumulator = 0
                    elif k == 'o':
                        self.play_dir = "REV" if self.play_dir == "FWD" else "FWD"
                    elif k == 'x':
                        if self.speed_idx < len(self.speeds) - 1: self.speed_idx += 1
                    elif k == 'z':
                        if self.speed_idx > 0: self.speed_idx -= 1
                    elif k == 'n':
                        self.auto_play = False
                        self.accumulator = 0
                        if self.op_idx < self.total_ops:
                            self.exec_op(self.ops[self.op_idx])
                            self.op_idx += 1
                    elif k == 'b':
                        self.auto_play = False
                        self.accumulator = 0
                        if self.op_idx > 0:
                            self.op_idx -= 1
                            self.exec_inv_op(self.ops[self.op_idx])
                    elif k == 'g':
                        if not self.has_ops and not self.has_nums:
                            self.generate_data()
                    elif k == 'm':
                        if not self.has_ops:
                            self.flag_idx = (self.flag_idx + 1) % len(self.flags)
                            self.generate_data()
                    elif k == 'a':
                        if not self.has_ops and not self.has_nums:
                            self.change_elems(-1)
                    elif k == 's':
                        if not self.has_ops and not self.has_nums:
                            self.change_elems(1)
                    elif k == 'd':
                        if not self.has_ops and not self.has_nums:
                            self.change_disorder(-1)
                    elif k == 'f':
                        if not self.has_ops and not self.has_nums:
                            self.change_disorder(1)
                    elif k == 'e':
                        self.check_ordered()
                        self.force_redraw = True
                    elif k == 'c':
                        if not self.has_ops and self.target_executable is not None:
                            self.show_make_screen(make_re=False)
                    elif k == 'q':
                        break

# ==========================================
# MAIN ENTRY
# ==========================================
def main():
    target, elements, max_disorder, ops_path, nums_path = parse_arguments()
    visualizer = PushSwapVisualizer(target, elements, max_disorder, ops_path, nums_path)
    visualizer.run()


if __name__ == "__main__":
    main()
