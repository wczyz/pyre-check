# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast
import subprocess
import unittest
from textwrap import dedent
from typing import List
from unittest.mock import call, patch

from ..filesystem import Target, TargetCollector, Filesystem, MercurialBackedFilesystem


class FilesystemTest(unittest.TestCase):
    def assert_collector(
        self, source: str, expected_targets: List[Target], pyre_only: bool
    ) -> None:
        target_collector = TargetCollector(pyre_only)
        tree = ast.parse(dedent(source))
        target_collector.visit(tree)
        targets = target_collector.result()
        self.assertEqual(expected_targets, targets)

    def test_target_collector(self) -> None:
        source = """
        load("@path:python_binary.bzl", "python_binary")

        python_binary(
            name = "target_name",
            main_module = "path.to.module",
            deps = [
                ":dependency_target_name",
            ],
        )
        """
        expected_targets = []
        self.assert_collector(source, expected_targets, False)

        source = """
        load("@path:python_binary.bzl", "python_binary")

        python_binary(
            name = "target_name",
            main_module = "path.to.module",
            typing = "False",
            deps = [
                ":dependency_target_name",
            ],
        )
        """
        expected_targets = [
            Target("target_name", strict=False, pyre=True, check_types=False),
        ]
        self.assert_collector(source, expected_targets, False)

        source = """
        load("@path:python_binary.bzl", "python_binary")

        python_binary(
            name = "target_name",
            main_module = "path.to.module",
            check_types_options = "strict",
            deps = [
                ":dependency_target_name",
            ],
        )
        """
        expected_targets = [
            Target("target_name", strict=True, pyre=True, check_types=False),
        ]
        self.assert_collector(source, expected_targets, False)

        source = """
        load("@path:python_binary.bzl", "python_binary")

        python_binary(
            name = "target_name",
            main_module = "path.to.module",
            check_types = True,
            deps = [
                ":dependency_target_name",
            ],
        )

        python_unittest(
            name = "test_target_name",
            srcs = glob([
                "**/tests/*.py",
            ]),
            check_types = False,
            deps = [
                ":dependency_target_name",
            ],
        )
        """
        expected_targets = [
            Target("target_name", strict=False, pyre=True, check_types=True),
            Target("test_target_name", strict=False, pyre=True, check_types=False),
        ]
        self.assert_collector(source, expected_targets, False)

        source = """
        load("@path:python_binary.bzl", "python_binary")

        python_binary(
            name = "target_name",
            main_module = "path.to.module",
            check_types = True,
            deps = [
                ":dependency_target_name",
            ],
        )

        python_unittest(
            name = "test_target_name",
            srcs = glob([
                "**/tests/*.py",
            ]),
            check_types = True,
            deps = [
                ":dependency_target_name",
            ],
        )
        """
        expected_targets = [
            Target("target_name", strict=False, pyre=True, check_types=True),
            Target("test_target_name", strict=False, pyre=True, check_types=True),
        ]
        self.assert_collector(source, expected_targets, False)

        source = """
        load("@path:python_binary.bzl", "python_binary")

        python_binary(
            name = "target_name",
            main_module = "path.to.module",
            check_types = True,
            deps = [
                ":dependency_target_name",
            ],
        )

        python_unittest(
            name = "test_target_name",
            srcs = glob([
                "**/tests/*.py",
            ]),
            check_types = True,
            check_types_options = "mypy",
            deps = [
                ":dependency_target_name",
            ],
        )
        """
        expected_targets = [
            Target("target_name", strict=False, pyre=True, check_types=True)
        ]
        self.assert_collector(source, expected_targets, True)

        source = """
        load("@path:python_binary.bzl", "python_binary")

        python_binary(
            name = "target_name",
            main_module = "path.to.module",
            check_types = True,
            deps = [
                ":dependency_target_name",
            ],
        )

        python_unittest(
            name = "test_target_name",
            srcs = glob([
                "**/tests/*.py",
            ]),
            check_types = True,
            check_types_options = "strict, mypy",
            deps = [
                ":dependency_target_name",
            ],
        )
        """
        expected_targets = [
            Target("target_name", strict=False, pyre=True, check_types=True)
        ]
        self.assert_collector(source, expected_targets, True)

    def test_filesystem_list_bare(self) -> None:
        filesystem = Filesystem()

        with patch.object(subprocess, "run") as run:
            filesystem.list(".", [".pyre_configuration.local"])
            run.assert_has_calls(
                [
                    call(
                        ["find", ".", "(", "-path", "./.pyre_configuration.local", ")"],
                        stdout=subprocess.PIPE,
                        cwd=".",
                    ),
                    call().stdout.decode("utf-8"),
                    call().stdout.decode().split(),
                ]
            )

        with patch.object(subprocess, "run") as run:
            filesystem.list("/root", ["**/*.py", "foo.cpp"], exclude=["bar/*.py"])
            run.assert_has_calls(
                [
                    call(
                        [
                            "find",
                            ".",
                            "(",
                            "-path",
                            "./**/*.py",
                            "-or",
                            "-path",
                            "./foo.cpp",
                            ")",
                            "-and",
                            "!",
                            "(",
                            "-path",
                            "./bar/*.py",
                            ")",
                        ],
                        stdout=subprocess.PIPE,
                        cwd="/root",
                    ),
                    call().stdout.decode("utf-8"),
                    call().stdout.decode().split(),
                ]
            )

        def fail_command(
            *args: object, **kwargs: object
        ) -> "subprocess.CompletedProcess[bytes]":
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="".encode("utf-8")
            )

        with patch.object(subprocess, "run") as run:
            run.side_effect = fail_command
            self.assertEqual([], filesystem.list(".", [".pyre_configuration.local"]))
            run.assert_has_calls(
                [
                    call(
                        ["find", ".", "(", "-path", "./.pyre_configuration.local", ")"],
                        stdout=subprocess.PIPE,
                        cwd=".",
                    )
                ]
            )

    def test_filesystem_list_mercurial(self) -> None:
        filesystem = MercurialBackedFilesystem()

        with patch.object(subprocess, "run") as run:
            filesystem.list(".", [".pyre_configuration.local"])
            run.assert_has_calls(
                [
                    call(
                        ["hg", "files", "--include", ".pyre_configuration.local"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        cwd=".",
                    ),
                    call().stdout.decode("utf-8"),
                    call().stdout.decode().split(),
                ]
            )

        with patch.object(subprocess, "run") as run:
            filesystem.list("/root", ["**/*.py", "foo.cpp"], exclude=["bar/*.py"])
            run.assert_has_calls(
                [
                    call(
                        [
                            "hg",
                            "files",
                            "--include",
                            "**/*.py",
                            "--include",
                            "foo.cpp",
                            "--exclude",
                            "bar/*.py",
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        cwd="/root",
                    ),
                    call().stdout.decode("utf-8"),
                    call().stdout.decode().split(),
                ]
            )

        def fail_command(
            *args: object, **kwargs: object
        ) -> "subprocess.CompletedProcess[bytes]":
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="".encode("utf-8")
            )

        with patch.object(subprocess, "run") as run:
            run.side_effect = fail_command
            self.assertEqual([], filesystem.list(".", [".pyre_configuration.local"]))
            run.assert_has_calls(
                [
                    call(
                        ["hg", "files", "--include", ".pyre_configuration.local"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        cwd=".",
                    )
                ]
            )
