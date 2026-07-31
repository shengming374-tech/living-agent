# 参考检出 / Reference checkouts

`maibot/` 是官方 `Mai-with-u/MaiBot` 仓库的忽略、只读浅检出，只用于机制研究，不会被 LivingAgent 打包、导入或作为运行依赖。精确修订和查阅文件记录在 `docs/research/provenance.md`；删除该检出不会影响 LivingAgent 运行时。

`maibot/` is an ignored, read-only shallow checkout of the official
`Mai-with-u/MaiBot` repository. It exists only for mechanism research and is
not packaged, imported, or required by LivingAgent.

The exact revision and inspected files are recorded in
`docs/research/provenance.md`. Delete the checkout without affecting the
LivingAgent runtime.
