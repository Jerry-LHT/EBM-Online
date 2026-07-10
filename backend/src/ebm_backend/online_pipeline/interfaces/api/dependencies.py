"""API dependency construction."""

from __future__ import annotations

from ebm_backend.online_pipeline.application.use_cases.module_use_case_facade import (
    ModuleUseCaseFacade,
)
from ebm_backend.online_pipeline.application.use_cases.run_q2pico import RunQ2PICO
from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import (
    RunSearchRetrieval,
)
from ebm_backend.online_pipeline.application.use_cases.run_study_screening import (
    RunStudyScreening,
)
from ebm_backend.online_pipeline.infrastructure.methods.q2pico.factory import (
    build_q2pico_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.resolver import (
    RegistryModuleMethodResolver,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.factory import (
    build_search_mesh_mapping_method,
    build_search_retrieval_method,
    build_search_textword_expansion_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.factory import (
    build_study_screening_method,
)


def get_module_use_case_facade_for_api() -> ModuleUseCaseFacade:
    return ModuleUseCaseFacade(resolver=RegistryModuleMethodResolver())


def get_q2pico_use_case_for_api(*, method_name: str) -> RunQ2PICO:
    return RunQ2PICO(method=build_q2pico_method(method_name=method_name))


def get_search_retrieval_use_case_for_api(
    *,
    method_name: str,
    mesh_method_name: str | None,
    textword_method_name: str | None,
) -> RunSearchRetrieval:
    return RunSearchRetrieval(
        retrieval_method=build_search_retrieval_method(method_name=method_name),
        mesh_mapping_method=build_search_mesh_mapping_method(method_name=mesh_method_name),
        textword_expansion_method=build_search_textword_expansion_method(
            method_name=textword_method_name
        ),
    )


def get_study_screening_use_case_for_api(*, method_name: str) -> RunStudyScreening:
    return RunStudyScreening(method=build_study_screening_method(method_name=method_name))
