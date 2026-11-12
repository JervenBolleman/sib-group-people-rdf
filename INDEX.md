# SIB people and groups

This page holds a graph of SIB groups, the people in them, their papers and the courses they gave. It was built from public pages on sib.swiss and uses schema.org terms. The SIB itself is the organization [ROR 002n09z45](https://ror.org/002n09z45).

A person with an ORCID iD is named by that iD. Everyone else is named by their sib.swiss directory page. Papers and courses are linked to people by name, so a few links may be wrong.

## Data

```sib-data
```

The whole graph is also available as [Turtle](data/sib.ttl), [N-Triples](data/sib.nt), [JSON-LD](data/sib.jsonld) and [RDF/XML](data/sib.rdf).

## Graph

Every person, group, paper and course in the data. People are shown with their sib.swiss photo. Hover a node to see its neighbours, click it for details.

```sib-graph
```

## Questions

### Who gave the most courses?

Counts the distinct courses each person was an instructor for.

```sparql
PREFIX schema: <https://schema.org/>

SELECT ?person ?name (COUNT(DISTINCT ?course) AS ?courses) WHERE {
  ?course a schema:CourseInstance ;
          schema:instructor ?person .
  ?person schema:name ?name .
}
GROUP BY ?person ?name
ORDER BY DESC(?courses)
```

### Which groups train the most?

Counts the courses that had at least one instructor from each group.

```sparql
PREFIX schema: <https://schema.org/>

SELECT ?groupName (COUNT(DISTINCT ?course) AS ?courses) WHERE {
  ?course a schema:CourseInstance ;
          schema:instructor ?person .
  ?person schema:memberOf ?group .
  ?group schema:name ?groupName .
}
GROUP BY ?groupName
ORDER BY DESC(?courses)
```

### Which groups co-train?

Pairs of different groups whose members taught the same course together.

```sparql
PREFIX schema: <https://schema.org/>

SELECT ?groupA ?groupB (COUNT(DISTINCT ?course) AS ?courses) WHERE {
  ?course a schema:CourseInstance ;
          schema:instructor ?p1, ?p2 .
  ?p1 schema:memberOf ?a .
  ?p2 schema:memberOf ?b .
  ?a schema:name ?groupA .
  ?b schema:name ?groupB .
  FILTER(?p1 != ?p2 && STR(?groupA) < STR(?groupB))
}
GROUP BY ?groupA ?groupB
ORDER BY DESC(?courses)
```

### Which groups co-publish?

Pairs of different groups, with the number of papers that had an author from each group.

```sparql
PREFIX schema: <https://schema.org/>

SELECT ?groupA ?groupB (COUNT(DISTINCT ?paper) AS ?papers) WHERE {
  ?paper a schema:ScholarlyArticle ;
         schema:author ?p1, ?p2 .
  ?p1 schema:memberOf ?a .
  ?p2 schema:memberOf ?b .
  ?a schema:name ?groupA .
  ?b schema:name ?groupB .
  FILTER(?p1 != ?p2 && STR(?groupA) < STR(?groupB))
}
GROUP BY ?groupA ?groupB
ORDER BY DESC(?papers)
LIMIT 50
```

### Who taught together?

Pairs of people who were instructors on the same course.

```sparql
PREFIX schema: <https://schema.org/>

SELECT ?nameA ?nameB (COUNT(DISTINCT ?course) AS ?courses) WHERE {
  ?course a schema:CourseInstance ;
          schema:instructor ?a, ?b .
  ?a schema:name ?nameA .
  ?b schema:name ?nameB .
  FILTER(STR(?nameA) < STR(?nameB))
}
GROUP BY ?nameA ?nameB
ORDER BY DESC(?courses)
LIMIT 50
```

### Who wrote the most papers?

Counts the distinct papers each person is an author of.

```sparql
PREFIX schema: <https://schema.org/>

SELECT ?person ?name (COUNT(DISTINCT ?paper) AS ?papers) WHERE {
  ?paper a schema:ScholarlyArticle ;
         schema:author ?person .
  ?person schema:name ?name .
}
GROUP BY ?person ?name
ORDER BY DESC(?papers)
LIMIT 50
```

### Who has an ORCID iD?

People whose node is their ORCID iD. Everyone else is still identified by their sib.swiss directory page.

```sparql
PREFIX schema: <https://schema.org/>

SELECT ?person ?name WHERE {
  ?person a schema:Person ;
          schema:name ?name .
  FILTER(STRSTARTS(STR(?person), "https://orcid.org/"))
}
ORDER BY ?name
```
