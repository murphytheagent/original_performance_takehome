"""
# Anthropic's Original Performance Engineering Take-home (Release version)

Copyright Anthropic PBC 2026. Permission is granted to modify and use, but not
to publish or redistribute your solutions so it's hard to find spoilers.

# Task

- Optimize the kernel (in KernelBuilder.build_kernel) as much as possible in the
  available time, as measured by test_kernel_cycles on a frozen separate copy
  of the simulator.

Validate your results using `python tests/submission_tests.py` without modifying
anything in the tests/ folder.

We recommend you look through problem.py next.
"""

import random
import unittest

from problem import (
    Engine,
    DebugInfo,
    SLOT_LIMITS,
    VLEN,
    N_CORES,
    SCRATCH_SIZE,
    Machine,
    Tree,
    Input,
    HASH_STAGES,
    reference_kernel,
    build_mem_image,
    reference_kernel2,
)


class KernelBuilder:
    def __init__(self):
        self.instrs = []
        self.scratch = {}
        self.scratch_debug = {}
        self.scratch_ptr = 0
        self.const_map = {}
        self.vector_const_map = {}

    def debug_info(self):
        return DebugInfo(scratch_map=self.scratch_debug)

    def build(self, slots: list[tuple[Engine, tuple]], vliw: bool = False):
        # Simple slot packing that just uses one slot per instruction bundle
        instrs = []
        for engine, slot in slots:
            instrs.append({engine: [slot]})
        return instrs

    def add(self, engine, slot):
        self.instrs.append({engine: [slot]})

    def emit(self, **engines):
        instr = {}
        for engine, slots in engines.items():
            if slots:
                instr[engine] = list(slots)
        if instr:
            self.instrs.append(instr)

    def alloc_scratch(self, name=None, length=1):
        addr = self.scratch_ptr
        if name is not None:
            self.scratch[name] = addr
            self.scratch_debug[addr] = (name, length)
        self.scratch_ptr += length
        assert self.scratch_ptr <= SCRATCH_SIZE, "Out of scratch space"
        return addr

    def scratch_const(self, val, name=None):
        if val not in self.const_map:
            addr = self.alloc_scratch(name)
            self.add("load", ("const", addr, val))
            self.const_map[val] = addr
        return self.const_map[val]

    def scratch_vconst(self, val, name=None):
        if val not in self.vector_const_map:
            scalar = self.scratch_const(val, None if name is None else f"{name}_scalar")
            addr = self.alloc_scratch(name, VLEN)
            self.emit(valu=[("vbroadcast", addr, scalar)])
            self.vector_const_map[val] = addr
        return self.vector_const_map[val]

    def _emit_packed_const_broadcasts(self, specs, scalar_tmps, final_loads=None):
        if not specs:
            return

        width = len(scalar_tmps)
        pending = []
        idx = 0
        while idx < len(specs):
            chunk = specs[idx : idx + width]
            self.emit(
                load=[
                    ("const", scalar_tmps[temp_i], value)
                    for temp_i, (value, _dest) in enumerate(chunk)
                ],
                valu=[
                    ("vbroadcast", dest, scalar_tmps[temp_i])
                    for temp_i, (_value, dest) in enumerate(pending)
                ],
            )
            pending = chunk
            idx += len(chunk)

        self.emit(
            load=[] if final_loads is None else final_loads,
            valu=[
                ("vbroadcast", dest, scalar_tmps[temp_i])
                for temp_i, (_value, dest) in enumerate(pending)
            ],
        )

    def _emit_packed_contiguous_node_preloads(
        self,
        dests,
        *,
        start_addr,
        addr_tmps,
        value_tmps,
        stride_const,
        final_loads=None,
    ):
        if not dests:
            return

        width = min(len(addr_tmps), len(value_tmps))
        assert width >= 2, "preload pipeline expects at least two lanes of staging"

        self.emit(
            load=[
                ("const", addr_tmps[0], start_addr),
                ("const", addr_tmps[1], start_addr + 1),
            ]
        )

        pending = []
        next_idx = 0
        while next_idx < len(dests):
            chunk = dests[next_idx : next_idx + width]
            alu_slots = []
            if len(chunk) == width and next_idx + len(chunk) < len(dests):
                alu_slots = [
                    ("+", addr_tmps[temp_i], addr_tmps[temp_i], stride_const)
                    for temp_i in range(width)
                ]
            self.emit(
                load=[
                    ("load", value_tmps[temp_i], addr_tmps[temp_i])
                    for temp_i in range(len(chunk))
                ],
                valu=[
                    ("vbroadcast", dest, value_tmps[temp_i])
                    for temp_i, dest in enumerate(pending)
                ],
                alu=alu_slots,
            )
            pending = chunk
            next_idx += len(chunk)

        self.emit(
            load=[] if final_loads is None else final_loads,
            valu=[
                ("vbroadcast", dest, value_tmps[temp_i])
                for temp_i, dest in enumerate(pending)
            ],
        )

    def _schedule_ops(self, ops):
        by_id = {op["id"]: op for op in ops}
        remaining = set(by_id)
        done = set()
        while remaining:
            instr = {}
            cycle_done = set(done)
            completed_this_cycle = []
            for engine in ("alu", "valu", "load", "store", "flow"):
                limit = SLOT_LIMITS[engine]
                ready = [
                    by_id[op_id]
                    for op_id in remaining
                    if by_id[op_id]["engine"] == engine
                    and all(dep in cycle_done for dep in by_id[op_id]["deps"])
                ]
                def sort_key(op):
                    if engine == "valu":
                        return (-op["group"], op["stage"], op["priority"], op["id"])
                    return (
                        op["group"],
                        op["stage"],
                        op["priority"],
                        op["id"],
                    )

                ready.sort(key=sort_key)
                picked = ready[:limit]
                if not picked:
                    continue

                instr[engine] = [op["slot"] for op in picked]
                for op in picked:
                    remaining.remove(op["id"])
                    completed_this_cycle.append(op["id"])

            assert instr, "Scheduler stalled on a cyclic dependency graph"
            done.update(completed_this_cycle)
            self.instrs.append(instr)

    def _append_vector_round_ops(
        self,
        ops,
        next_id,
        groups,
        depth,
        is_final,
        *,
        use_cached_nodes=False,
        cache_next_nodes=False,
        state_deps=None,
    ):
        if state_deps is None:
            state_deps = [[] for _ in groups]

        def add_op(engine, slot, deps, group, stage, priority=0):
            nonlocal next_id
            op_id = next_id
            next_id += 1
            ops.append(
                {
                    "id": op_id,
                    "engine": engine,
                    "slot": slot,
                    "deps": list(deps),
                    "group": group,
                    "stage": stage,
                    "priority": priority,
                }
            )
            return op_id

        def add_bit_mask(dest, src, bit_const, shift_const, deps, group, stage):
            bit_id = add_op(
                "valu",
                ("&", dest, src, bit_const),
                deps,
                group,
                stage,
            )
            if shift_const is not None:
                bit_id = add_op(
                    "valu",
                    (">>", dest, dest, shift_const),
                    [bit_id],
                    group,
                    stage + 1,
                )
                stage += 1
            return add_op(
                "valu",
                ("-", dest, self.zero_vec, dest),
                [bit_id],
                group,
                stage + 1,
            )

        next_state_deps = []
        for local_group, block in enumerate(groups):
            round_start = list(state_deps[local_group])
            val = self.value_blocks[block]
            path = self.wave_path[local_group]
            addr = self.wave_addr[local_group]
            node = self.wave_node[local_group]
            tmp1 = self.wave_tmp1[local_group]
            tmp2 = self.wave_tmp2[local_group]
            tmp3 = self.wave_tmp3[local_group]
            node_deps = []
            if depth == 0:
                node_src = self.root_vec
            elif depth in (1, 2, 3):
                assert use_cached_nodes, "shallow rounds should use cached node vectors"
                node_src = node
            else:
                addr_id = add_op(
                    "valu",
                    ("+", addr, path, self.base_vecs[depth]),
                    round_start,
                    local_group,
                    0,
                )
                for lane in range(VLEN):
                    node_deps.append(
                        add_op(
                            "load",
                            ("load_offset", node, addr, lane),
                            [addr_id],
                            local_group,
                            1,
                            lane,
                        )
                    )
                node_src = node

            xor_id = add_op(
                "valu",
                ("^", val, val, node_src),
                round_start + node_deps,
                local_group,
                2,
            )
            stage0_id = add_op(
                "valu",
                ("multiply_add", val, val, self.mul_4097_vec, self.hash_add0_vec),
                [xor_id],
                local_group,
                3,
            )
            stage1_left = add_op(
                "valu",
                ("^", tmp1, val, self.hash_xor1_vec),
                [stage0_id],
                local_group,
                4,
            )
            stage1_right = add_op(
                "valu",
                (">>", tmp2, val, self.shift_19_vec),
                [stage0_id],
                local_group,
                4,
                1,
            )
            stage1_merge = add_op(
                "valu",
                ("^", val, tmp1, tmp2),
                [stage1_left, stage1_right],
                local_group,
                5,
            )
            stage2_id = add_op(
                "valu",
                ("multiply_add", val, val, self.mul_33_vec, self.hash_add2_vec),
                [stage1_merge],
                local_group,
                6,
            )
            stage3_left = add_op(
                "valu",
                ("+", tmp1, val, self.hash_add3_vec),
                [stage2_id],
                local_group,
                7,
            )
            stage3_right = add_op(
                "valu",
                ("<<", tmp2, val, self.shift_9_vec),
                [stage2_id],
                local_group,
                7,
                1,
            )
            stage3_merge = add_op(
                "valu",
                ("^", val, tmp1, tmp2),
                [stage3_left, stage3_right],
                local_group,
                8,
            )
            stage4_id = add_op(
                "valu",
                ("multiply_add", val, val, self.mul_9_vec, self.hash_add4_vec),
                [stage3_merge],
                local_group,
                9,
            )
            stage5_left = add_op(
                "valu",
                ("^", tmp1, val, self.hash_xor5_vec),
                [stage4_id],
                local_group,
                10,
            )
            stage5_right = add_op(
                "valu",
                (">>", tmp2, val, self.shift_16_vec),
                [stage4_id],
                local_group,
                10,
                1,
            )
            hash_done = add_op(
                "valu",
                ("^", val, tmp1, tmp2),
                [stage5_left, stage5_right],
                local_group,
                11,
            )

            if is_final or depth == self.forest_height:
                next_state_deps.append([hash_done])
                continue

            parity_id = add_op(
                "valu",
                ("&", path if depth == 0 else addr, val, self.one_vec),
                [hash_done],
                local_group,
                12,
            )
            if depth == 0:
                next_path_id = parity_id
            else:
                next_path_id = add_op(
                    "valu",
                    ("multiply_add", path, path, self.two_vec, addr),
                    [parity_id],
                    local_group,
                    13,
                )

            carry_deps = [hash_done, next_path_id]
            if depth == 0 and self.forest_height >= 1:
                table_id = add_op(
                    "flow",
                    ("vselect", node, path, self.depth1_alt_vec, self.depth1_base_vec),
                    [next_path_id],
                    local_group,
                    14,
                )
                if cache_next_nodes:
                    carry_deps.append(table_id)
                else:
                    add_op(
                        "store",
                        ("vstore", self.depth1_table_addrs[block], node),
                        [table_id],
                        local_group,
                        15,
                    )
            elif depth == 1 and self.forest_height >= 2:
                lo_mask_id = add_op(
                    "valu",
                    ("&", tmp1, path, self.one_vec),
                    [next_path_id],
                    local_group,
                    14,
                )
                hi_mask_id = add_op(
                    "valu",
                    ("&", tmp2, path, self.two_vec),
                    [next_path_id],
                    local_group,
                    14,
                    1,
                )
                left_id = add_op(
                    "flow",
                    (
                        "vselect",
                        addr,
                        tmp1,
                        self.depth2_left_alt_vec,
                        self.depth2_left_base_vec,
                    ),
                    [lo_mask_id],
                    local_group,
                    15,
                )
                right_id = add_op(
                    "flow",
                    (
                        "vselect",
                        node,
                        tmp1,
                        self.depth2_right_alt_vec,
                        self.depth2_right_base_vec,
                    ),
                    [lo_mask_id],
                    local_group,
                    16,
                )
                table_id = add_op(
                    "flow",
                    ("vselect", node, tmp2, node, addr),
                    [left_id, right_id, hi_mask_id],
                    local_group,
                    17,
                )
                if cache_next_nodes:
                    carry_deps.append(table_id)
                else:
                    add_op(
                        "store",
                        ("vstore", self.depth2_table_addrs[block], node),
                        [table_id],
                        local_group,
                        18,
                    )
            elif depth == 2 and self.forest_height >= 3:
                lo01_id = add_op(
                    "valu",
                    ("&", tmp1, path, self.one_vec),
                    [next_path_id],
                    local_group,
                    14,
                )
                mid01_id = add_op(
                    "valu",
                    ("&", tmp2, path, self.two_vec),
                    [next_path_id],
                    local_group,
                    14,
                    1,
                )
                hi_id = add_op(
                    "valu",
                    ("&", tmp3, path, self.four_vec),
                    [next_path_id],
                    local_group,
                    14,
                    2,
                )
                pair01_id = add_op(
                    "flow",
                    ("vselect", node, tmp1, self.depth3_nodes[1], self.depth3_nodes[0]),
                    [lo01_id],
                    local_group,
                    15,
                )
                pair23_id = add_op(
                    "flow",
                    ("vselect", addr, tmp1, self.depth3_nodes[3], self.depth3_nodes[2]),
                    [lo01_id],
                    local_group,
                    16,
                )
                upper_half0_id = add_op(
                    "flow",
                    ("vselect", node, tmp2, addr, node),
                    [mid01_id, pair01_id, pair23_id],
                    local_group,
                    17,
                )
                pair45_id = add_op(
                    "flow",
                    ("vselect", addr, tmp1, self.depth3_nodes[5], self.depth3_nodes[4]),
                    [upper_half0_id],
                    local_group,
                    18,
                )
                pair67_id = add_op(
                    "flow",
                    ("vselect", tmp1, tmp1, self.depth3_nodes[7], self.depth3_nodes[6]),
                    [upper_half0_id],
                    local_group,
                    19,
                )
                upper_half1_id = add_op(
                    "flow",
                    ("vselect", addr, tmp2, tmp1, addr),
                    [pair45_id, pair67_id],
                    local_group,
                    20,
                )
                table_id = add_op(
                    "flow",
                    ("vselect", node, tmp3, addr, node),
                    [hi_id, upper_half0_id, upper_half1_id],
                    local_group,
                    21,
                )
                if cache_next_nodes:
                    carry_deps.append(table_id)

            next_state_deps.append(carry_deps)

        return next_id, next_state_deps

    def _build_vector_round_sequence(self, groups, round_specs):
        ops = []
        next_id = 0
        state_deps = [[] for _ in groups]
        for round_spec in round_specs:
            next_id, state_deps = self._append_vector_round_ops(
                ops,
                next_id,
                groups,
                round_spec["depth"],
                round_spec["is_final"],
                use_cached_nodes=round_spec.get("use_cached_nodes", False),
                cache_next_nodes=round_spec.get("cache_next_nodes", False),
                state_deps=state_deps,
            )
        self._schedule_ops(ops)

    def _append_stream_io_ops(
        self,
        ops,
        next_id,
        *,
        pairs,
        addr_regs,
        kind,
        group_base,
        stage_base,
    ):
        def add_op(engine, slot, deps, group, stage, priority=0):
            nonlocal next_id
            op_id = next_id
            next_id += 1
            ops.append(
                {
                    "id": op_id,
                    "engine": engine,
                    "slot": slot,
                    "deps": list(deps),
                    "group": group,
                    "stage": stage,
                    "priority": priority,
                }
            )
            return op_id

        addr0, addr1 = addr_regs
        addr_deps = []
        for pair_i, (block0, block1) in enumerate(pairs):
            stage = stage_base + pair_i
            group = group_base + pair_i
            io_deps = list(addr_deps)
            if kind == "load":
                add_op("load", ("vload", self.value_blocks[block0], addr0), io_deps, group, stage)
                add_op(
                    "load",
                    ("vload", self.value_blocks[block1], addr1),
                    io_deps,
                    group,
                    stage,
                    1,
                )
            else:
                add_op("store", ("vstore", addr0, self.value_blocks[block0]), io_deps, group, stage)
                add_op(
                    "store",
                    ("vstore", addr1, self.value_blocks[block1]),
                    io_deps,
                    group,
                    stage,
                    1,
                )

            if pair_i + 1 < len(pairs):
                inc0 = add_op("alu", ("+", addr0, addr0, self.pair_stride), io_deps, group, stage, 2)
                inc1 = add_op(
                    "alu",
                    ("+", addr1, addr1, self.pair_stride),
                    io_deps,
                    group,
                    stage,
                    3,
                )
                addr_deps = [inc0, inc1]

        return next_id

    def _build_vector_round_sequence_with_io(
        self,
        groups,
        round_specs,
        *,
        prefetch_pairs=None,
        prefetch_addr_regs=None,
        store_pairs=None,
        store_addr_regs=None,
    ):
        ops = []
        next_id = 0
        state_deps = [[] for _ in groups]
        for round_spec in round_specs:
            next_id, state_deps = self._append_vector_round_ops(
                ops,
                next_id,
                groups,
                round_spec["depth"],
                round_spec["is_final"],
                use_cached_nodes=round_spec.get("use_cached_nodes", False),
                cache_next_nodes=round_spec.get("cache_next_nodes", False),
                state_deps=state_deps,
            )

        io_group_base = len(groups) + 1000
        if prefetch_pairs:
            next_id = self._append_stream_io_ops(
                ops,
                next_id,
                pairs=prefetch_pairs,
                addr_regs=prefetch_addr_regs,
                kind="load",
                group_base=io_group_base,
                stage_base=1000,
            )
            io_group_base += len(prefetch_pairs) + 1
        if store_pairs:
            next_id = self._append_stream_io_ops(
                ops,
                next_id,
                pairs=store_pairs,
                addr_regs=store_addr_regs,
                kind="store",
                group_base=io_group_base,
                stage_base=1100,
            )

        self._schedule_ops(ops)

    def _build_vector_wave(
        self,
        groups,
        depth,
        is_final,
        *,
        use_cached_nodes=False,
        cache_next_nodes=False,
    ):
        self._build_vector_round_sequence(
            groups,
            [
                {
                    "depth": depth,
                    "is_final": is_final,
                    "use_cached_nodes": use_cached_nodes,
                    "cache_next_nodes": cache_next_nodes,
                }
            ],
        )

    def _build_vector_kernel(
        self, forest_height: int, n_nodes: int, batch_size: int, rounds: int
    ):
        self.forest_height = forest_height
        forest_values_p = 7
        inp_indices_p = forest_values_p + n_nodes
        inp_values_p = inp_indices_p + batch_size
        n_blocks = batch_size // VLEN
        wave_size = min(16, n_blocks)

        packed_vconsts = []

        def alloc_packed_vconst(value, name):
            addr = self.alloc_scratch(name, VLEN)
            packed_vconsts.append((value, addr))
            return addr

        self.zero_vec = alloc_packed_vconst(0, "zero_vec")
        self.one_vec = alloc_packed_vconst(1, "one_vec")
        self.two_vec = alloc_packed_vconst(2, "two_vec")
        self.four_vec = alloc_packed_vconst(4, "four_vec")
        self.mul_4097_vec = alloc_packed_vconst(4097, "mul_4097_vec")
        self.mul_33_vec = alloc_packed_vconst(33, "mul_33_vec")
        self.mul_9_vec = alloc_packed_vconst(9, "mul_9_vec")
        self.hash_add0_vec = alloc_packed_vconst(HASH_STAGES[0][1], "hash_add0_vec")
        self.hash_xor1_vec = alloc_packed_vconst(HASH_STAGES[1][1], "hash_xor1_vec")
        self.hash_add2_vec = alloc_packed_vconst(HASH_STAGES[2][1], "hash_add2_vec")
        self.hash_add3_vec = alloc_packed_vconst(HASH_STAGES[3][1], "hash_add3_vec")
        self.hash_add4_vec = alloc_packed_vconst(HASH_STAGES[4][1], "hash_add4_vec")
        self.hash_xor5_vec = alloc_packed_vconst(HASH_STAGES[5][1], "hash_xor5_vec")
        self.shift_19_vec = alloc_packed_vconst(HASH_STAGES[1][4], "shift_19_vec")
        self.shift_9_vec = alloc_packed_vconst(HASH_STAGES[3][4], "shift_9_vec")
        self.shift_16_vec = alloc_packed_vconst(HASH_STAGES[5][4], "shift_16_vec")

        self.base_vecs = {}
        for depth in range(4, forest_height + 1):
            self.base_vecs[depth] = alloc_packed_vconst(
                forest_values_p + (1 << depth) - 1, f"base_vec_{depth}"
            )

        self.value_blocks = [
            self.alloc_scratch(f"value_block_{block}", VLEN) for block in range(n_blocks)
        ]
        self.wave_path = [
            self.alloc_scratch(f"wave_path_{i}", VLEN) for i in range(wave_size)
        ]
        self.wave_addr = [
            self.alloc_scratch(f"wave_addr_{i}", VLEN) for i in range(wave_size)
        ]
        self.wave_node = [
            self.alloc_scratch(f"wave_node_{i}", VLEN) for i in range(wave_size)
        ]
        self.wave_tmp1 = [
            self.alloc_scratch(f"wave_tmp1_{i}", VLEN) for i in range(wave_size)
        ]
        self.wave_tmp2 = [
            self.alloc_scratch(f"wave_tmp2_{i}", VLEN) for i in range(wave_size)
        ]
        self.wave_tmp3 = [
            self.alloc_scratch(f"wave_tmp3_{i}", VLEN) for i in range(wave_size)
        ]
        self.pair_stride = self.alloc_scratch("pair_stride")
        shallow_stride = self.alloc_scratch("shallow_stride")
        value_addr0 = self.alloc_scratch("value_addr0")
        value_addr1 = self.alloc_scratch("value_addr1")
        init_scalar0 = self.alloc_scratch("init_scalar0")
        init_scalar1 = self.alloc_scratch("init_scalar1")

        shallow_nodes = {
            node_idx: self.alloc_scratch(f"shallow_node_{node_idx}", VLEN)
            for node_idx in range(15)
        }

        self._emit_packed_const_broadcasts(
            packed_vconsts,
            [init_scalar0, init_scalar1],
            final_loads=[
                ("const", self.pair_stride, VLEN * 2),
                ("const", shallow_stride, 2),
            ],
        )
        self._emit_packed_contiguous_node_preloads(
            [shallow_nodes[node_idx] for node_idx in range(15)],
            start_addr=forest_values_p,
            addr_tmps=[value_addr0, value_addr1],
            value_tmps=[init_scalar0, init_scalar1],
            stride_const=shallow_stride,
            final_loads=[
                ("const", value_addr0, inp_values_p),
                ("const", value_addr1, inp_values_p + VLEN),
            ],
        )

        self.root_vec = shallow_nodes[0]
        self.depth1_base_vec = shallow_nodes[1]
        self.depth1_alt_vec = shallow_nodes[2]
        self.depth2_left_base_vec = shallow_nodes[3]
        self.depth2_left_alt_vec = shallow_nodes[4]
        self.depth2_right_base_vec = shallow_nodes[5]
        self.depth2_right_alt_vec = shallow_nodes[6]
        self.depth3_nodes = [shallow_nodes[node_idx] for node_idx in range(7, 15)]

        first_wave_blocks = n_blocks if rounds == 0 else min(wave_size, n_blocks)
        for block in range(0, first_wave_blocks, 2):
            load_slots = [("vload", self.value_blocks[block], value_addr0)]
            if block + 1 < n_blocks:
                load_slots.append(("vload", self.value_blocks[block + 1], value_addr1))
            alu_slots = []
            if block + 2 < first_wave_blocks:
                alu_slots.append(("+", value_addr0, value_addr0, self.pair_stride))
                alu_slots.append(("+", value_addr1, value_addr1, self.pair_stride))
            self.emit(load=load_slots, alu=alu_slots)

        round_idx = 0
        while round_idx < rounds:
            remaining_rounds = rounds - round_idx
            fused_rounds = remaining_rounds
            round_specs = []
            for offset in range(fused_rounds):
                depth = offset % (forest_height + 1)
                round_specs.append(
                    {
                        "depth": depth,
                        "is_final": remaining_rounds == offset + 1,
                        "use_cached_nodes": depth in (1, 2, 3),
                        "cache_next_nodes": depth in (0, 1, 2) and offset + 1 < fused_rounds,
                    }
                )

            for block in range(0, n_blocks, wave_size):
                groups = list(range(block, min(block + wave_size, n_blocks)))
                prefetch_pairs = None
                if block + wave_size < n_blocks:
                    next_groups = list(
                        range(block + wave_size, min(block + 2 * wave_size, n_blocks))
                    )
                    if len(next_groups) >= 2:
                        prefetch_pairs = [
                            (next_groups[pair_i], next_groups[pair_i + 1])
                            for pair_i in range(0, len(next_groups), 2)
                        ]
                        self.emit(
                            load=[
                                ("const", value_addr0, inp_values_p + next_groups[0] * VLEN),
                                ("const", value_addr1, inp_values_p + (next_groups[0] + 1) * VLEN),
                            ]
                        )

                store_pairs = None
                if block >= wave_size:
                    prev_groups = list(range(block - wave_size, block))
                    store_pairs = [
                        (prev_groups[pair_i], prev_groups[pair_i + 1])
                        for pair_i in range(0, len(prev_groups), 2)
                    ]
                    self.emit(
                        load=[
                            ("const", init_scalar0, inp_values_p + prev_groups[0] * VLEN),
                            ("const", init_scalar1, inp_values_p + (prev_groups[0] + 1) * VLEN),
                        ]
                    )

                self._build_vector_round_sequence_with_io(
                    groups,
                    round_specs,
                    prefetch_pairs=prefetch_pairs,
                    prefetch_addr_regs=(value_addr0, value_addr1),
                    store_pairs=store_pairs,
                    store_addr_regs=(init_scalar0, init_scalar1),
                )
            round_idx += fused_rounds

        final_store_start = 0 if rounds == 0 else max(0, n_blocks - wave_size)
        self.emit(
            load=[
                ("const", value_addr0, inp_values_p + final_store_start * VLEN),
                ("const", value_addr1, inp_values_p + (final_store_start + 1) * VLEN),
            ]
        )
        for block in range(final_store_start, n_blocks, 2):
            store_slots = [("vstore", value_addr0, self.value_blocks[block])]
            if block + 1 < n_blocks:
                store_slots.append(
                    (
                        "vstore",
                        value_addr1,
                        self.value_blocks[block + 1],
                    )
                )
            alu_slots = []
            if block + 2 < n_blocks:
                alu_slots.append(("+", value_addr0, value_addr0, self.pair_stride))
                alu_slots.append(("+", value_addr1, value_addr1, self.pair_stride))
            self.emit(store=store_slots, alu=alu_slots)

    def build_hash(self, val_hash_addr, tmp1, tmp2, round, i):
        slots = []

        for hi, (op1, val1, op2, op3, val3) in enumerate(HASH_STAGES):
            slots.append(("alu", (op1, tmp1, val_hash_addr, self.scratch_const(val1))))
            slots.append(("alu", (op3, tmp2, val_hash_addr, self.scratch_const(val3))))
            slots.append(("alu", (op2, val_hash_addr, tmp1, tmp2)))
            slots.append(("debug", ("compare", val_hash_addr, (round, i, "hash_stage", hi))))

        return slots

    def _build_scalar_kernel(
        self, forest_height: int, n_nodes: int, batch_size: int, rounds: int
    ):
        """
        Like reference_kernel2 but building actual instructions.
        Scalar implementation using only scalar ALU and load/store.
        """
        tmp1 = self.alloc_scratch("tmp1")
        tmp2 = self.alloc_scratch("tmp2")
        tmp3 = self.alloc_scratch("tmp3")
        # Scratch space addresses
        init_vars = [
            "rounds",
            "n_nodes",
            "batch_size",
            "forest_height",
            "forest_values_p",
            "inp_indices_p",
            "inp_values_p",
        ]
        for v in init_vars:
            self.alloc_scratch(v, 1)
        for i, v in enumerate(init_vars):
            self.add("load", ("const", tmp1, i))
            self.add("load", ("load", self.scratch[v], tmp1))

        zero_const = self.scratch_const(0)
        one_const = self.scratch_const(1)
        two_const = self.scratch_const(2)

        # Pause instructions are matched up with yield statements in the reference
        # kernel to let you debug at intermediate steps. The testing harness in this
        # file requires these match up to the reference kernel's yields, but the
        # submission harness ignores them.
        self.add("flow", ("pause",))
        # Any debug engine instruction is ignored by the submission simulator
        self.add("debug", ("comment", "Starting loop"))

        body = []  # array of slots

        # Scalar scratch registers
        tmp_idx = self.alloc_scratch("tmp_idx")
        tmp_val = self.alloc_scratch("tmp_val")
        tmp_node_val = self.alloc_scratch("tmp_node_val")
        tmp_addr = self.alloc_scratch("tmp_addr")

        for round in range(rounds):
            for i in range(batch_size):
                i_const = self.scratch_const(i)
                # idx = mem[inp_indices_p + i]
                body.append(("alu", ("+", tmp_addr, self.scratch["inp_indices_p"], i_const)))
                body.append(("load", ("load", tmp_idx, tmp_addr)))
                body.append(("debug", ("compare", tmp_idx, (round, i, "idx"))))
                # val = mem[inp_values_p + i]
                body.append(("alu", ("+", tmp_addr, self.scratch["inp_values_p"], i_const)))
                body.append(("load", ("load", tmp_val, tmp_addr)))
                body.append(("debug", ("compare", tmp_val, (round, i, "val"))))
                # node_val = mem[forest_values_p + idx]
                body.append(("alu", ("+", tmp_addr, self.scratch["forest_values_p"], tmp_idx)))
                body.append(("load", ("load", tmp_node_val, tmp_addr)))
                body.append(("debug", ("compare", tmp_node_val, (round, i, "node_val"))))
                # val = myhash(val ^ node_val)
                body.append(("alu", ("^", tmp_val, tmp_val, tmp_node_val)))
                body.extend(self.build_hash(tmp_val, tmp1, tmp2, round, i))
                body.append(("debug", ("compare", tmp_val, (round, i, "hashed_val"))))
                # idx = 2*idx + (1 if val % 2 == 0 else 2)
                body.append(("alu", ("%", tmp1, tmp_val, two_const)))
                body.append(("alu", ("==", tmp1, tmp1, zero_const)))
                body.append(("flow", ("select", tmp3, tmp1, one_const, two_const)))
                body.append(("alu", ("*", tmp_idx, tmp_idx, two_const)))
                body.append(("alu", ("+", tmp_idx, tmp_idx, tmp3)))
                body.append(("debug", ("compare", tmp_idx, (round, i, "next_idx"))))
                # idx = 0 if idx >= n_nodes else idx
                body.append(("alu", ("<", tmp1, tmp_idx, self.scratch["n_nodes"])))
                body.append(("flow", ("select", tmp_idx, tmp1, tmp_idx, zero_const)))
                body.append(("debug", ("compare", tmp_idx, (round, i, "wrapped_idx"))))
                # mem[inp_indices_p + i] = idx
                body.append(("alu", ("+", tmp_addr, self.scratch["inp_indices_p"], i_const)))
                body.append(("store", ("store", tmp_addr, tmp_idx)))
                # mem[inp_values_p + i] = val
                body.append(("alu", ("+", tmp_addr, self.scratch["inp_values_p"], i_const)))
                body.append(("store", ("store", tmp_addr, tmp_val)))

        body_instrs = self.build(body)
        self.instrs.extend(body_instrs)
        # Required to match with the yield in reference_kernel2
        self.instrs.append({"flow": [("pause",)]})

    def build_kernel(
        self, forest_height: int, n_nodes: int, batch_size: int, rounds: int
    ):
        if N_CORES == 1 and batch_size % VLEN == 0 and batch_size <= 256:
            self._build_vector_kernel(forest_height, n_nodes, batch_size, rounds)
        else:
            self._build_scalar_kernel(forest_height, n_nodes, batch_size, rounds)

BASELINE = 147734

def do_kernel_test(
    forest_height: int,
    rounds: int,
    batch_size: int,
    seed: int = 123,
    trace: bool = False,
    prints: bool = False,
):
    print(f"{forest_height=}, {rounds=}, {batch_size=}")
    random.seed(seed)
    forest = Tree.generate(forest_height)
    inp = Input.generate(forest, batch_size, rounds)
    mem = build_mem_image(forest, inp)

    kb = KernelBuilder()
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), rounds)
    # print(kb.instrs)

    value_trace = {}
    machine = Machine(
        mem,
        kb.instrs,
        kb.debug_info(),
        n_cores=N_CORES,
        value_trace=value_trace,
        trace=trace,
    )
    machine.prints = prints
    for i, ref_mem in enumerate(reference_kernel2(mem, value_trace)):
        machine.run()
        inp_values_p = ref_mem[6]
        if prints:
            print(machine.mem[inp_values_p : inp_values_p + len(inp.values)])
            print(ref_mem[inp_values_p : inp_values_p + len(inp.values)])
        assert (
            machine.mem[inp_values_p : inp_values_p + len(inp.values)]
            == ref_mem[inp_values_p : inp_values_p + len(inp.values)]
        ), f"Incorrect result on round {i}"
        inp_indices_p = ref_mem[5]
        if prints:
            print(machine.mem[inp_indices_p : inp_indices_p + len(inp.indices)])
            print(ref_mem[inp_indices_p : inp_indices_p + len(inp.indices)])
        # Updating these in memory isn't required, but you can enable this check for debugging
        # assert machine.mem[inp_indices_p:inp_indices_p+len(inp.indices)] == ref_mem[inp_indices_p:inp_indices_p+len(inp.indices)]

    print("CYCLES: ", machine.cycle)
    print("Speedup over baseline: ", BASELINE / machine.cycle)
    return machine.cycle


class Tests(unittest.TestCase):
    def test_ref_kernels(self):
        """
        Test the reference kernels against each other
        """
        random.seed(123)
        for i in range(10):
            f = Tree.generate(4)
            inp = Input.generate(f, 10, 6)
            mem = build_mem_image(f, inp)
            reference_kernel(f, inp)
            for _ in reference_kernel2(mem, {}):
                pass
            assert inp.indices == mem[mem[5] : mem[5] + len(inp.indices)]
            assert inp.values == mem[mem[6] : mem[6] + len(inp.values)]

    def test_kernel_trace(self):
        # Full-scale example for performance testing
        do_kernel_test(10, 16, 256, trace=True, prints=False)

    # Passing this test is not required for submission, see submission_tests.py for the actual correctness test
    # You can uncomment this if you think it might help you debug
    # def test_kernel_correctness(self):
    #     for batch in range(1, 3):
    #         for forest_height in range(3):
    #             do_kernel_test(
    #                 forest_height + 2, forest_height + 4, batch * 16 * VLEN * N_CORES
    #             )

    def test_kernel_cycles(self):
        do_kernel_test(10, 16, 256)


# To run all the tests:
#    python perf_takehome.py
# To run a specific test:
#    python perf_takehome.py Tests.test_kernel_cycles
# To view a hot-reloading trace of all the instructions:  **Recommended debug loop**
# NOTE: The trace hot-reloading only works in Chrome. In the worst case if things aren't working, drag trace.json onto https://ui.perfetto.dev/
#    python perf_takehome.py Tests.test_kernel_trace
# Then run `python watch_trace.py` in another tab, it'll open a browser tab, then click "Open Perfetto"
# You can then keep that open and re-run the test to see a new trace.

# To run the proper checks to see which thresholds you pass:
#    python tests/submission_tests.py

if __name__ == "__main__":
    unittest.main()
