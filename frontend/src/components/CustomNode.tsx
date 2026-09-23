import { memo } from 'react';
import {Handle, Position, NodeToolbar, type NodeToolbarProps} from '@xyflow/react';

type CustomNodeProps = NodeToolbarProps & { data: {label: string, description?: string} }

const CustomNode = (props: CustomNodeProps) => {
    return (
        <>
            <NodeToolbar position={props.position} className="custom-node-tooltip">
                <div>
                    {props.data.description}
                </div>
            </NodeToolbar>

            <div style={{ padding: '10px 20px' }}>
                {props.data.label}
            </div>

            <Handle type="source" id="top" position={Position.Top} />
            <Handle type="target" id="ttop" position={Position.Top} />
            <Handle type="target" id="bottom" position={Position.Bottom} />
            <Handle type="target" id="left" position={Position.Left} />
            <Handle type="source" id="right" position={Position.Right} />
        </>
    );
};

export default memo(CustomNode);