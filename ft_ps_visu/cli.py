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
    if len(sys.argv) < 2 or len(sys.argv) > 4:
        print(f"Usage: {sys.argv[0]} <path_to_push_swap> [number_of_elements] [max_disorder_percentage]")
        sys.exit(1)
        
    target_executable = sys.argv[1]
    if not os.path.isfile(target_executable) or not os.access(target_executable, os.X_OK):
        print(f"Error: '{target_executable}' is not a valid or executable file.")
        sys.exit(1)
        
    n_elems = 500
    if len(sys.argv) >= 3:
        try:
            n_elems = int(sys.argv[2])
            if n_elems <= 0:
                raise ValueError
        except ValueError:
            print("Error: number_of_elements must be a positive integer.")
            sys.exit(1)
            
    max_disorder = 50
    if len(sys.argv) == 4:
        try:
            max_disorder = int(sys.argv[3])
            if max_disorder < 0 or max_disorder > 55:
                raise ValueError
        except ValueError:
            print("Error: max_disorder_percentage must be between 0 and 55.")
            sys.exit(1)
            
    return target_executable, n_elems, max_disorder

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
    def __init__(self, target_executable, n_elems, max_disorder):
        self.target_executable = target_executable
        self.n_elems = n_elems
        self.disorder = max_disorder
        self.actual_disorder = 0.0
        
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
        
        sys.stdout.write("\033[2J\033[H\033[1;36mGenerating data and running push_swap... Please wait.\033[0m\r\n")
        sys.stdout.flush()

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
        
        top_items = [
            (len("push_swap visualizer"), f"{c_cyan}push_swap visualizer{c_rst}"),
            (len(f"Nums: {self.n_elems}"), f"{c_yellow}Nums: {self.n_elems}{c_rst}"),
            (len(f"Mode: {mode_str}"), f"{c_green}Mode: {mode_str}{c_rst}"),
            (len(f"Disorder: {self.actual_disorder:.1f}%"), f"{c_magenta}Disorder: {self.actual_disorder:.1f}%{c_rst}"),
            (len(f"Ops: {self.op_idx}/{self.total_ops}"), f"{c_bold}Ops: {self.op_idx}/{self.total_ops}{c_rst}"),
            (len(f"Auto: {auto_str} ({self.play_dir})"), f"Auto: {auto_col}{auto_str}{c_rst} ({dir_col}{self.play_dir}{c_rst})"),
            (len(f"Speed: {speed_val}/s"), f"{c_bold}Speed: {speed_val}/s{c_rst}")
        ]
        
        bottom_items = [
            (len("[P] Play/Pause"), f"[{c_dim}P{c_rst}] Play/Pause"),
            (len("[O] Fwd/Rev"), f"[{c_dim}O{c_rst}] Fwd/Rev"),
            (len("[N] Next"), f"[{c_dim}N{c_rst}] Next"),
            (len("[B] Back"), f"[{c_dim}B{c_rst}] Back"),
            (len("[Z] Speed-"), f"[{c_dim}Z{c_rst}] Speed-"),
            (len("[X] Speed+"), f"[{c_dim}X{c_rst}] Speed+"),
            (len("[G] Re-gen"), f"[{c_yellow}G{c_rst}] Re-gen"),
            (len("[M] Mode"), f"[{c_green}M{c_rst}] Mode"),
            (len("[A] Nums-"), f"[{c_cyan}A{c_rst}] Nums-"),
            (len("[S] Nums+"), f"[{c_cyan}S{c_rst}] Nums+"),
            (len("[D] Disorder-"), f"[{c_magenta}D{c_rst}] Disorder-"),
            (len("[F] Disorder+"), f"[{c_magenta}F{c_rst}] Disorder+"),
            (len("[Q] Quit"), f"[{c_red}Q{c_rst}] Quit")
        ]
        
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
                        self.generate_data()
                    elif k == 'm':
                        self.flag_idx = (self.flag_idx + 1) % len(self.flags)
                        self.generate_data()
                    elif k == 'a':
                        self.change_elems(-1)
                    elif k == 's':
                        self.change_elems(1)
                    elif k == 'd':
                        self.change_disorder(-1)
                    elif k == 'f':
                        self.change_disorder(1)
                    elif k == 'q':
                        break

# ==========================================
# MAIN ENTRY
# ==========================================
def main():
    target, elements, max_disorder = parse_arguments()
    visualizer = PushSwapVisualizer(target, elements, max_disorder)
    visualizer.run()


if __name__ == "__main__":
    main()
