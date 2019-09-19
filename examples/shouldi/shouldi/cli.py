import sys

from dffml.df.types import Input
from dffml.df.base import operation_in, opimp_in, Operation
from dffml.df.memory import MemoryOrchestrator
from dffml.df.linker import Linker
from dffml.operation.output import GetSingle
from dffml.util.cli.cmd import CMD
from dffml.util.cli.arg import Arg

from shouldi.bandit import run_bandit
from shouldi.pypi import pypi_latest_package_version
from shouldi.pypi import pypi_package_json
from shouldi.pypi import pypi_package_url
from shouldi.pypi import pypi_package_contents
from shouldi.safety import safety_check

# sys.modules[__name__] is a list of everything we've imported in this file.
# opimp_in returns a subset of that list, any OperationImplementations
OPIMPS = opimp_in(sys.modules[__name__])


class Install(CMD):

    arg_packages = Arg(
        "packages", nargs="+", help="Package to check if we should install"
    )

    async def run(self):
        # Create an Orchestrator which will manage the running of our operations
        async with MemoryOrchestrator.basic_config(*OPIMPS) as orchestrator:
            # Create a orchestrator context, everything in DFFML follows this
            # one-two context entry pattern
            async with orchestrator() as octx:
                for package_name in self.packages:
                    # For each package add a new input set to the network of
                    # inputs (ictx). Operations run under a context, the context
                    # here is the package_name to evaluate (the first argument).
                    # The next arguments are all the inputs we're seeding the
                    # network with for that context. We give the package name
                    # because pypi_latest_package_version needs it to find the
                    # version, which safety will then use. We also give an input
                    # to the output operation GetSingle, which takes a list of
                    # data type definitions we want to select as our results.
                    await octx.ictx.sadd(
                        package_name,
                        Input(
                            value=package_name,
                            definition=pypi_package_json.op.inputs["package"],
                        ),
                        Input(
                            value=[
                                safety_check.op.outputs["issues"].name,
                                run_bandit.op.outputs["report"].name,
                            ],
                            definition=GetSingle.op.inputs["spec"],
                        ),
                    )

                # Run all the operations, Each iteration of this loop happens
                # when all inputs are exhausted for a context, the output
                # operations are then run and their results are yielded
                async for ctx, results in octx.run_operations():
                    # The context for this data flow was the package name
                    package_name = (await ctx.handle()).as_string()
                    # Get the results of the GetSingle output operation
                    results = results[GetSingle.op.name]
                    # Check if any of the values of the operations evaluate to
                    # true, so if the number of issues found by safety is
                    # non-zero then this will be true
                    any_issues = list(results.values())
                    if (
                        any_issues[0] > 0
                        or any_issues[1]["CONFIDENCE.HIGH_AND_SEVERITY.HIGH"]
                        > 5
                    ):
                        print(f"Do not install {package_name}! {results!r}")
                    else:
                        print(f"{package_name} is okay to install")


class LinkerTest(CMD):
    arg_path_info = Arg(
        "path_info",
        nargs="+",
        help="end and start points for finding a back path",
    )

    async def export(self):
        linker = Linker()
        exported = linker.export(
            run_bandit.op,
            pypi_latest_package_version.op,
            pypi_package_json.op,
            pypi_package_url.op,
            pypi_package_contents.op,
            safety_check.op,
        )
        return exported

    ##TODO Multiple INPUT and Multiple OUTPUT cases
    async def run(self):
        temp = await self.export()
        dest_operation = self.path_info[0]
        init_inp = self.path_info[1]
        operations_dict = temp["operations"]
        for name, operation in operations_dict.items():
            operation["inputs"] = list(operation["inputs"].values())[0]
            operation["outputs"] = list(operation["outputs"].values())[0]
        inp = operations_dict[dest_operation]["inputs"]
        backtrack_list = [dest_operation]
        while inp != init_inp:
            for name, operation in operations_dict.items():
                if operation["outputs"] == inp:
                    backtrack_list.append(name)
                    inp = operation["inputs"]

        backtrack_list.reverse()
        return backtrack_list


class ShouldI(CMD):

    install = Install
    linker = LinkerTest
