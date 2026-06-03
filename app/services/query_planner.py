import re
import structlog

logger = structlog.get_logger()


class QueryPlanner:
    CTE_INDICATORS = {
        "compare": "Needs CTE: comparing two aggregations requires separate computation",
        "versus": "Needs CTE: comparing two values requires separate computation",
        "vs": "Needs CTE: comparing two values requires separate computation",
        "difference between": "Needs CTE: difference requires two separate computations",
        "trend": "Needs CTE: trends require time-series aggregation then windowing",
        "running total": "Needs CTE: running totals need pre-aggregation then window function",
        "cumulative": "Needs CTE: cumulative values need pre-aggregation then window function",
        "rank": "Needs CTE: ranking with additional context needs pre-aggregation",
        "percentile": "Needs CTE: percentile calculation needs full dataset first",
        "over budget": "Needs CTE: budget comparison requires salary aggregation then join",
        "above average": "Needs CTE: comparing to average requires computing average first",
        "below average": "Needs CTE: comparing to average requires computing average first",
        "overall average": "Needs CTE: overall average must be computed separately",
        "for each.*and also": "Needs CTE: multiple independent aggregations per group",
    }

    SUBQUERY_INDICATORS = {
        "highest.*in each": "Needs correlated subquery: finding max within each group",
        "lowest.*in each": "Needs correlated subquery: finding min within each group",
        "more than.*average": "Needs subquery: filtering by computed average",
        "greater than.*total": "Needs subquery: filtering by computed total",
    }

    AGGREGATION_WORDS = {
        "total", "sum", "average", "avg", "count", "how many",
        "maximum", "max", "minimum", "min", "most", "least",
        "percentage", "percent", "rate", "ratio",
    }

    GROUP_BY_WORDS = {
        "by", "per", "each", "every", "for each", "grouped by",
        "breakdown", "distribution", "across",
    }

    ORDER_WORDS = {
        "top", "bottom", "best", "worst", "highest", "lowest",
        "first", "last", "ranked",
    }

    def plan(self, question: str, num_tables: int, join_count: int) -> dict:
        """
        BEAVER Subtask 5: Query Decomposition.

        Analyzes the question to produce a query plan that tells the LLM
        exactly what structure to use.

        Args:
            question: The user's natural language question
            num_tables: Number of tables retrieved
            join_count: Number of join conditions found

        Returns:
            Query plan dict with structure recommendation:
            {
                "complexity": "simple" | "moderate" | "complex",
                "strategy": "direct" | "subquery" | "cte",
                "reason": "why this strategy was chosen",
                "needs_aggregation": True/False,
                "needs_group_by": True/False,
                "needs_order": True/False,
                "needs_limit": True/False,
                "suggested_cte_count": 0-3,
                "decomposition_hints": ["hint1", "hint2"]
            }
        """
        question_lower = question.lower()
        plan = {
            "complexity": "simple",
            "strategy": "direct",
            "reason": "",
            "needs_aggregation": False,
            "needs_group_by": False,
            "needs_order": False,
            "needs_limit": False,
            "suggested_cte_count": 0,
            "decomposition_hints": [],
        }

        for word in self.AGGREGATION_WORDS:
            if word in question_lower:
                plan["needs_aggregation"] = True
                break

        for word in self.GROUP_BY_WORDS:
            if word in question_lower:
                plan["needs_group_by"] = True
                break

        for word in self.ORDER_WORDS:
            if word in question_lower:
                plan["needs_order"] = True
                break

        if re.search(r'\btop\s+\d+\b', question_lower):
            plan["needs_limit"] = True
        if re.search(r'\bfirst\s+\d+\b', question_lower):
            plan["needs_limit"] = True

        for pattern, reason in self.CTE_INDICATORS.items():
            if re.search(pattern, question_lower):
                plan["strategy"] = "cte"
                plan["complexity"] = "complex"
                plan["reason"] = reason
                plan["suggested_cte_count"] = 2
                plan["decomposition_hints"].append(
                    f"Use WITH clause because: {reason}"
                )
                break

        if plan["strategy"] == "direct":
            for pattern, reason in self.SUBQUERY_INDICATORS.items():
                if re.search(pattern, question_lower):
                    plan["strategy"] = "subquery"
                    plan["complexity"] = "moderate"
                    plan["reason"] = reason
                    plan["decomposition_hints"].append(
                        f"Use correlated subquery because: {reason}"
                    )
                    break

        complexity_score = 0
        if num_tables >= 4:
            complexity_score += 2
        elif num_tables >= 3:
            complexity_score += 1

        if join_count >= 3:
            complexity_score += 2
        elif join_count >= 2:
            complexity_score += 1

        if plan["needs_aggregation"] and plan["needs_group_by"]:
            complexity_score += 1

        if plan["needs_order"] and plan["needs_limit"]:
            complexity_score += 1
        if complexity_score >= 4 and plan["strategy"] == "direct":
            plan["strategy"] = "cte"
            plan["complexity"] = "complex"
            plan["reason"] = f"High structural complexity (score={complexity_score}): {num_tables} tables, {join_count} joins"
            plan["suggested_cte_count"] = 1
        elif complexity_score >= 2 and plan["complexity"] == "simple":
            plan["complexity"] = "moderate"
            if not plan["reason"]:
                plan["reason"] = f"Moderate complexity: {num_tables} tables, {join_count} joins with aggregation"
        if not plan["reason"]:
            plan["reason"] = "Simple query: direct SELECT with basic joins"
        logger.info("query_planned",
                     complexity=plan["complexity"],
                     strategy=plan["strategy"],
                     tables=num_tables,
                     joins=join_count)
        return plan
