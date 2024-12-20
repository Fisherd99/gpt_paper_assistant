import configparser
import dataclasses
import json
from datetime import datetime, timedelta
from html import unescape
from typing import List, Optional
import re
import arxiv

import feedparser
from dataclasses import dataclass


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


@dataclass
class Paper:
    # paper class should track the list of authors, paper title, abstract, arxiv id
    authors: List[str]
    title: str
    abstract: str
    arxiv_id: str

    # add a hash function using arxiv_id
    def __hash__(self):
        return hash(self.arxiv_id)


def is_earlier(ts1, ts2):
    # compares two arxiv ids, returns true if ts1 is older than ts2
    return int(ts1.replace(".", "")) < int(ts2.replace(".", ""))


def get_papers_from_arxiv_api(area: str, timestamp, last_id, config: dict) -> List[Paper]:
    # look for papers that are newer than the newest papers in RSS.
    # we do this by looking at last_id and grabbing everything newer.
    end_date = timestamp
    start_date = timestamp - timedelta(days=int(config["FILTERING"]["duration_day"]))
    start_date2 = timestamp - timedelta(days=60)

    author_list = config["FILTERING"]["author_list"].split(",")
    author_query = " OR ".join([f'au:"{author.strip()}"' for author in author_list])
    print("author_query:",author_query)
    search = arxiv.Search( # according to area OR author
        query="(("
        + area
        + ") AND (submittedDate:["
        + start_date.strftime("%Y%m%d")
        + "* TO "
        + end_date.strftime("%Y%m%d")
        + "*])) OR ((" + author_query
        + ") AND (submittedDate:["
        + start_date2.strftime("%Y%m%d")
        + "* TO "
        + end_date.strftime("%Y%m%d")
        + "*]))",
        max_results=None,
        sort_by=arxiv.SortCriterion.SubmittedDate,
    )
    results = list(arxiv.Client().results(search))
    api_papers = []
    for result in results:
        new_id = result.get_short_id()[:10]
        #if is_earlier(last_id, new_id): #comment by Fisherd 2024-12-21
        if True:
            authors = [author.name for author in result.authors]
            summary = result.summary
            summary = unescape(re.sub("\n", " ", summary))
            paper = Paper(
                authors=authors,
                title=result.title,
                abstract=summary,
                arxiv_id=result.get_short_id()[:10],
            )
            api_papers.append(paper)
    return api_papers


def get_papers_from_arxiv_rss(area: str, config: Optional[dict]) -> List[Paper]:
    # get the feed from http://export.arxiv.org/rss/ and use the updated timestamp to avoid duplicates
    updated = datetime.utcnow() - timedelta(days=1)
    # format this into the string format 'Fri, 03 Nov 2023 00:30:00 GMT'
    updated_string = updated.strftime("%a, %d %b %Y %H:%M:%S GMT")
    print("in rss: updated_string:",updated_string)
    feed = feedparser.parse(
        f"http://export.arxiv.org/rss/{area}", modified=updated_string
    )
    if feed.status == 304:
        if (config is not None) and config["OUTPUT"]["debug_messages"]:
            print("No new papers since " + updated_string + " for " + area)
        # if there are no new papers return an empty list
        return [], None, None
    # get the list of entries
    entries = feed.entries
    if len(feed.entries) == 0:
        print("No entries found for " + area)
        return [], None, None
    last_id = feed.entries[0].link.split("/")[-1]
    # parse last modified date
    timestamp = datetime.strptime(feed.feed["updated"], "%a, %d %b %Y %H:%M:%S +0000")
    paper_list = []
    for paper in entries:
        # remove the link part of the id
        id = paper.link.split("/")[-1]
        # ignore updated papers
        ann_type = paper["arxiv_announce_type"]
        if (config["FILTERING"].getboolean("force_new")): # add by Fisherd 2024-12-21
            if ann_type != "new":
                print(f"force_new: ignoring {ann_type}:{id}-{paper.title}")
                continue
        # extract area
        paper_area = paper.tags[0]["term"]
        # ignore papers not in primary area
        if (area != paper_area) and (config["FILTERING"].getboolean("force_primary")):
            print(f"in {area}, ignoring {paper_area}:{id}-{paper.title}")
            continue
        # otherwise make a new paper, for the author field make sure to strip the HTML tags
        authors = [
            unescape(re.sub("<[^<]+?>", "", author)).strip()
            for author in paper.author.replace("\n", ", ").split(",")
        ]
        # strip html tags from summary
        summary = re.sub("<[^<]+?>", "", paper.summary)
        summary = unescape(re.sub("\n", " ", summary))
        # strip the last pair of parentehses containing (arXiv:xxxx.xxxxx [area.XX])
        title = re.sub("\(arXiv:[0-9]+\.[0-9]+v[0-9]+ \[.*\]\)$", "", paper.title)
        # make a new paper
        new_paper = Paper(authors=authors, title=title, abstract=summary, arxiv_id=id)
        paper_list.append(new_paper)

    return paper_list, timestamp, last_id


def merge_paper_list(paper_list, api_paper_list):
    api_set = set([paper.arxiv_id for paper in api_paper_list])
    merged_paper_list = api_paper_list
    for paper in paper_list:
        if paper.arxiv_id not in api_set:
            merged_paper_list.append(paper)
    return merged_paper_list


def get_papers_from_arxiv_rss_api(area: str, config: Optional[dict]) -> List[Paper]:
    paper_list, timestamp, last_id = get_papers_from_arxiv_rss(area, config)
    print("in rss_api: timestamp for api from rss:",timestamp)
    if timestamp is None:
       return []
    api_paper_list = get_papers_from_arxiv_api(area, timestamp, last_id, config)
    merged_paper_list = merge_paper_list(paper_list, api_paper_list)
    return merged_paper_list


if __name__ == "__main__":## only for test
    config = configparser.ConfigParser()
    config.read("configs/config.ini")

    paper_list1, timestamp1, last_id1 = get_papers_from_arxiv_rss("physics.chem-ph", config)
    print("in __main__rss chem-ph:",timestamp1)
    print("rss find:", len(paper_list1), [paper.arxiv_id for paper in paper_list1])
    api_paper_list1 = get_papers_from_arxiv_api("physics.chem-ph", timestamp1, last_id1, config)
    print("api find:", len(api_paper_list1), [paper.arxiv_id for paper in api_paper_list1])

    merged_paper_list1 = merge_paper_list(paper_list1, api_paper_list1)
    print(len(merged_paper_list1),[paper.arxiv_id for paper in merged_paper_list1])
    paper_set = set(merged_paper_list1)

    paper_list2, timestamp2, last_id2 = get_papers_from_arxiv_rss("cond-mat.mtrl-sci", config)
    print("in __main__rss cond-mat:",timestamp2)
    print("rss find:", len(paper_list2), [paper.arxiv_id for paper in paper_list2])
    api_paper_list2 = get_papers_from_arxiv_api("cond-mat.mtrl-sci", timestamp2, last_id2, config)
    print("api find:", len(api_paper_list2), [paper.arxiv_id for paper in api_paper_list2])

    merged_paper_list2 = merge_paper_list(paper_list2, api_paper_list2)
    print(len(merged_paper_list2),[paper.arxiv_id for paper in merged_paper_list2])

    paper_set.update(set(merged_paper_list2))
    print(len(paper_set),[paper.arxiv_id for paper in paper_set])

    print("success")
