import math

import dgl.function as fn
import torch
import torch.nn as nn
import torch.nn.functional as F
from dgl.ops import edge_softmax


class HGTLayer(nn.Module):

    def __init__(self, in_dim, out_dim, ntypes, etypes, num_heads, dropout=0.2, use_norm=True):
        """HGT层

        :param in_dim: int 输入特征维数
        :param out_dim: int 输出特征维数
        :param ntypes: List[str] 顶点类型列表
        :param etypes: List[str] 边类型列表
        :param num_heads: int 注意力头数K
        :param dropout: dropout: float, optional Dropout概率，默认为0.2
        :param use_norm: bool, optional 是否使用层归一化，默认为True
        """
        super().__init__()
        self.out_dim = out_dim
        self.num_heads = num_heads
        self.d_k = out_dim // num_heads

        self.k_linears = nn.ModuleDict({ntype: nn.Linear(in_dim, out_dim) for ntype in ntypes})
        self.q_linears = nn.ModuleDict({ntype: nn.Linear(in_dim, out_dim) for ntype in ntypes})
        self.v_linears = nn.ModuleDict({ntype: nn.Linear(in_dim, out_dim) for ntype in ntypes})
        self.a_linears = nn.ModuleDict({ntype: nn.Linear(in_dim, out_dim) for ntype in ntypes})
        self.use_norm = use_norm
        if use_norm:
            self.norms = nn.ModuleDict({ntype: nn.LayerNorm(out_dim) for ntype in ntypes})

        self.mu = nn.ParameterDict({etype: nn.Parameter(torch.ones(num_heads)) for etype in etypes})
        self.w_att = nn.ParameterDict(
            {etype: nn.Parameter(torch.Tensor(num_heads, self.d_k, self.d_k)) for etype in etypes}
        )
        self.w_msg = nn.ParameterDict(
            {etype: nn.Parameter(torch.Tensor(num_heads, self.d_k, self.d_k)) for etype in etypes}
        )

        self.skip = nn.ParameterDict({ntype: nn.Parameter(torch.ones(1)) for ntype in ntypes})
        self.drop = nn.Dropout(dropout)
        self.reset_parameters()

    def reset_parameters(self):
        for etype in self.w_att:
            nn.init.xavier_uniform_(self.w_att[etype])
            nn.init.xavier_uniform_(self.w_msg[etype])

    def forward(self, g, feats):
        """
        :param g: DGLGraph 异构图
        :param feats: Dict[str, tensor(N_i, d_in)] 顶点类型到输入顶点特征的映射
        :return: Dict[str, tensor(N_i, d_out)] 顶点类型到输出特征的映射
        """
        if g.is_block:
            feats_dst = {ntype: feats[ntype][:g.num_dst_nodes(ntype)] for ntype in feats}
        else:
            feats_dst = feats
        with g.local_scope():
            for stype, etype, dtype in g.canonical_etypes:
                if g.num_edges(etype) == 0:
                    continue
                sg = g[stype, etype, dtype]
                feat_src, feat_dst = feats[stype], feats_dst[dtype]

                # (N_i, d_in) -> (N_i, d_out) -> (N_i, K, d_out/K)
                k = self.k_linears[stype](feat_src).view(-1, self.num_heads, self.d_k)
                v = self.v_linears[stype](feat_src).view(-1, self.num_heads, self.d_k)
                q = self.q_linears[dtype](feat_dst).view(-1, self.num_heads, self.d_k)

                # k[:, h] @= w_att[h] => k[n, h, j] = ∑(i) k[n, h, i] * w_att[h, i, j]
                k = torch.einsum('nhi,hij->nhj', k, self.w_att[etype])
                v = torch.einsum('nhi,hij->nhj', v, self.w_msg[etype])

                sg.srcdata.update({'k': k, f'v_{etype}': v})
                sg.dstdata['q'] = q

                # 第1步：异构互注意力
                sg.apply_edges(fn.v_dot_u('q', 'k', 't'))  # sg.edata['t']: (E, K, 1)
                attn = sg.edata.pop('t').squeeze(dim=-1) * self.mu[etype] / math.sqrt(self.d_k)
                attn = edge_softmax(sg, attn)  # (E, K)
                sg.edata['t'] = attn.unsqueeze(dim=-1)

            # 第2步：异构消息传递+目标相关的聚集
            g.multi_update_all({
                etype: (fn.u_mul_e(f'v_{etype}', 't', 'm'), fn.sum('m', 'h'))
                for etype in g.etypes if g.num_edges(etype) > 0
            }, 'mean')

            # 第3步：残差连接
            out_feats = {}
            for ntype in g.dsttypes:
                if g.num_dst_nodes(ntype) == 0:
                    continue
                alpha = torch.sigmoid(self.skip[ntype])
                h = g.dstnodes[ntype].data['h'].view(-1, self.out_dim)
                trans_out = self.drop(self.a_linears[ntype](h))
                out = alpha * trans_out + (1 - alpha) * feats_dst[ntype]
                out_feats[ntype] = self.norms[ntype](out) if self.use_norm else out
            return out_feats


class HGT(nn.Module):

    def __init__(
            self, in_dims, hidden_dim, out_dim, ntypes, etypes, num_heads,
            num_layers, predict_ntype, dropout=0.2, use_norm=True):
        """HGT模型

        :param in_dims: Dict[str, int] 顶点类型到输入特征维数的映射
        :param hidden_dim: int 隐含特征维数
        :param out_dim: int 输出特征维数
        :param ntypes: List[str] 顶点类型列表
        :param etypes: List[str] 边类型列表
        :param num_heads: int 注意力头数K
        :param num_layers: int 层数
        :param predict_ntype: str 待预测顶点类型
        :param dropout: dropout: float, optional Dropout概率，默认为0.2
        :param use_norm: bool, optional 是否使用层归一化，默认为True
        """
        super().__init__()
        self.predict_ntype = predict_ntype
        self.adapt_fcs = nn.ModuleDict({
            ntype: nn.Linear(in_dim, hidden_dim) for ntype, in_dim in in_dims.items()
        })
        self.layers = nn.ModuleList([
            HGTLayer(hidden_dim, hidden_dim, ntypes, etypes, num_heads, dropout, use_norm)
            for _ in range(num_layers)
        ])
        self.predict = nn.Linear(hidden_dim, out_dim)

    def forward(self, blocks, feats):
        """
        :param blocks: List[DGLBlock]
        :param feats: Dict[str, tensor(N_i, d_in)] 顶点类型到输入顶点特征的映射
        :return: tensor(N_i, d_out) 待预测顶点的最终嵌入
        """
        hs = {ntype: F.gelu(self.adapt_fcs[ntype](feats[ntype])) for ntype in feats}
        for i in range(len(self.layers)):
            hs = self.layers[i](blocks[i], hs)  # {ntype: tensor(N_i, d_hid)}
        out = self.predict(hs[self.predict_ntype])  # tensor(N_i, d_out)
        return out
