from pydantic import BaseModel, Field


class CandidateNode(BaseModel):
    node_id: str
    latitude: float
    longitude: float
    x: float | None = None
    y: float | None = None
    cluster_total_flow: float
    included_od_count: int
    source_k_values: list[int] = Field(default_factory=list)
    merged_count: int = 1


class CandidateEdge(BaseModel):
    edge_id: str
    from_node_id: str
    to_node_id: str
    straight_distance_km: float
    estimated_flow: float
    rank: int
    od_count: int = 0
    source: str = "all_od_weighted_kmeans"


class ODCandidateStats(BaseModel):
    source_name: str
    total_od_rows: int
    selected_top_percent: int | None = None
    selected_top_rows: int
    coordinate_excluded_rows: int
    non_positive_flow_excluded_rows: int = 0
    clustered_od_rows: int
    cluster_count_requested: int
    cluster_count_used: int
    iterative_cluster_counts: list[int] = Field(default_factory=list)
    pre_merge_node_count: int = 0
    merged_node_count: int = 0
    retained_node_count: int = 0
    pruned_node_count: int = 0
    low_impact_prune_percent: int | None = 20
    merge_distance_km: float = 3.0
    top_node_limit: int = 30
    edge_limit: int = 50
    min_estimated_flow: float | None = None
    sample_size: int | None = None
    flow_columns: list[str]
    flow_weights: dict[str, float] = Field(default_factory=dict)
    coordinate_columns: dict[str, str]
    coordinate_lookup_used: bool = False
    region_excluded_rows: int = 0
    region_filter_summary: dict = Field(default_factory=dict)
    elapsed_seconds: float = 0.0
    result_files: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ODCandidateResult(BaseModel):
    nodes: list[CandidateNode]
    edges: list[CandidateEdge]
    stats: ODCandidateStats
